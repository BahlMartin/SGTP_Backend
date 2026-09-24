"""
Controlador de Endpoints para Triage, Cola Multibox y Asignaciones.
"""
from typing import Any
from django.db import transaction
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from app.models.triage import (
    Box,
    Ticket,
    TicketEstudios,
    AsignacionesBox,
    EstadoTicket,
    EstadoBox,
)
from app.models.studies import Estudios
from app.schemas.triage import (
    BoxSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
)
from app.services.triage_service import (
    TriageService,
    TicketService,
    construir_orden_prioridad_case,
)
from app.core.permissions import (
    IsAdmisionOrJefa,
    IsBoxOrJefa,
    IsJefaRole,
)


class BoxViewSet(viewsets.ModelViewSet):
    """
    Gestión operativa de Boxes de atención asistencial.
    """
    queryset = Box.objects.all().order_by('numero')
    serializer_class = BoxSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'], url_path='llamar-siguiente', permission_classes=[IsBoxOrJefa])
    def llamar_siguiente(self, request: Request, pk: str = None) -> Response:
        """
        Llama al siguiente paciente disponible según el algoritmo multibox:
        Box 1 prioriza Discapacidad; Boxes 2..N excluyen Discapacidad.
        Ejecución atómica con select_for_update(skip_locked=True).
        """
        box = self.get_object()
        ticket, asignacion = TriageService.llamar_siguiente_paciente(
            box_id=box.id,
            personal=request.user
        )

        if not ticket:
            return Response(
                {
                    "mensaje": "No hay pacientes en cola de espera pendientes de atención para este Box.",
                    "box": BoxSerializer(box).data,
                    "ticket": None
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "mensaje": f"Paciente llamado con éxito al Box {box.numero}.",
                "ticket": TicketDetailSerializer(ticket).data,
                "asignacion_id": asignacion.id if asignacion else None
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='cerrar-atencion', permission_classes=[IsBoxOrJefa])
    def cerrar_atencion(self, request: Request, pk: str = None) -> Response:
        """
        Finaliza la atención en curso en el Box y lo deja en estado 'Disponible'.
        """
        box = self.get_object()
        serializer = CerrarAtencionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        asignacion = TriageService.cerrar_atencion(
            box_id=box.id,
            personal=request.user,
            motivo_cierre=serializer.validated_data.get('motivo_cierre')
        )

        # Refrescar box
        box.refresh_from_db()
        return Response(
            {
                "mensaje": f"Atención del Box {box.numero} finalizada.",
                "box": BoxSerializer(box).data,
                "asignacion": AsignacionesBoxSerializer(asignacion).data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], url_path='estado-general')
    def estado_general(self, request: Request) -> Response:
        """
        Monitoreo en tiempo real de todos los boxes para pantallas de sala y supervisión.
        """
        boxes = Box.objects.all().order_by('numero')
        return Response(BoxSerializer(boxes, many=True).data, status=status.HTTP_200_OK)


class TicketViewSet(viewsets.ModelViewSet):
    """
    Emisión, gestión y monitoreo de Tickets.
    - Creación en Admisión.
    - Edición protegida por ventana de 24 horas y rol 'Jefa'.
    - Borrado lógico (Soft-Delete).
    """
    queryset = Ticket.objects.all().select_related('paciente', 'personal_admision', 'box_actual').prefetch_related('estudios__estudio')
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TicketCreateSerializer
        return TicketDetailSerializer

    @transaction.atomic
    def perform_create(self, serializer: Any) -> None:
        estudios_ids = serializer.validated_data.pop('estudios_ids', [])
        ticket = serializer.save(personal_admision=self.request.user)

        # Asociar estudios seleccionados
        if estudios_ids:
            estudios_queryset = Estudios.objects.filter(id__in=estudios_ids, activo=True)
            for estudio in estudios_queryset:
                TicketEstudios.objects.create(ticket=ticket, estudio=estudio)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Aplica la regla de inmutabilidad de 24h y exclusividad para el rol 'Jefa'."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        # Validación e inmutabilidad en la capa de servicio
        ticket_modificado = TicketService.actualizar_ticket(
            ticket_id=instance.pk,
            usuario=request.user,
            datos=request.data
        )

        return Response(TicketDetailSerializer(ticket_modificado).data, status=status.HTTP_200_OK)

    def perform_destroy(self, instance: Ticket) -> None:
        """Borrado lógico asistencial."""
        instance.delete()

    @action(detail=False, methods=['get'], url_path='cola-espera')
    def cola_espera(self, request: Request) -> Response:
        """
        Devuelve los tickets pendientes ordenados según la prioridad asistencial y FIFO.
        """
        orden_medico = construir_orden_prioridad_case()
        tickets_pendientes = (
            Ticket.objects.filter(estado=EstadoTicket.PENDIENTE, is_deleted=False)
            .annotate(prioridad_peso=orden_medico)
            .order_by('prioridad_peso', 'fecha_hora_admision')
            .select_related('paciente', 'personal_admision')
            .prefetch_related('estudios__estudio')
        )
        serializer = TicketDetailSerializer(tickets_pendientes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AsignacionesBoxViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Historial inmutable de asignaciones y atenciones en Box.
    """
    queryset = AsignacionesBox.objects.all().select_related('box', 'personal', 'ticket').order_by('-fecha_hora_inicio')
    serializer_class = AsignacionesBoxSerializer
    permission_classes = [IsAuthenticated]


app_name = 'triage_endpoints'

router = DefaultRouter()
router.register(r'boxes', BoxViewSet, basename='boxes')
router.register(r'tickets', TicketViewSet, basename='tickets')
router.register(r'asignaciones', AsignacionesBoxViewSet, basename='asignaciones')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'BoxViewSet',
    'TicketViewSet',
    'AsignacionesBoxViewSet',
    'router',
    'urlpatterns',
]
