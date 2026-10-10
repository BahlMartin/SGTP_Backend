"""
Controlador de Endpoints para Emisión y Gestión de Tickets.
"""
from django.db import transaction
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from app.core.permissions import IsJefaRole
from app.core.validators import validar_formato_fecha
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    EstadoTicket,
)
from app.models.studies import Estudios
from app.schemas.ticket import (
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketHistorialDetailSerializer,
)
from app.services.ticket_service import TicketService
from app.services.triage_service import construir_orden_prioridad_case


class TicketViewSet(viewsets.ModelViewSet):
    """
    Emisión, gestión y monitoreo de Tickets.
    - Creación en Admisión.
    - Edición protegida por ventana de 24 horas y rol 'Jefa'.
    - Borrado lógico (Soft-Delete).
    """
    queryset = Ticket.objects.all().select_related(
        'paciente',
        'personal_admision',
        'box_actual'
    ).prefetch_related(
        'estudios__estudio',
        'asignaciones_historial__personal',
        'asignaciones_historial__box'
    )
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TicketCreateSerializer
        if self.action == 'retrieve':
            return TicketHistorialDetailSerializer
        return TicketDetailSerializer

    @transaction.atomic
    def perform_create(self, serializer) -> None:
        # Obtenemos los estudios antes de extraerlos
        estudios_ids = serializer.validated_data.get('estudios_ids', [])
        
        # --- NUEVA VALIDACIÓN ---
        # Si la lista está vacía (no mandaron estudios), cortamos la ejecución y devolvemos error 400
        if not estudios_ids:
            raise ValidationError({
                "detail": "No se puede admitir a un paciente ni crear un ticket sin seleccionar al menos un estudio."
            })
        # ------------------------

        estudios_ids = serializer.validated_data.pop('estudios_ids', [])
        ticket = serializer.save(personal_admision=self.request.user)

        # Asociar estudios seleccionados
        if estudios_ids:
            estudios_queryset = Estudios.objects.filter(id__in=estudios_ids, activo=True)
            for estudio in estudios_queryset:
                TicketEstudios.objects.create(ticket=ticket, estudio=estudio)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        ticket = serializer.instance
        headers = self.get_success_headers(serializer.data)
        return Response(TicketDetailSerializer(ticket).data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request: Request, *args, **kwargs) -> Response:
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

    @action(
        detail=False,
        methods=['get'],
        url_path='rendimiento-personal',
        permission_classes=[IsAuthenticated, IsJefaRole]
    )
    def rendimiento_personal(self, request: Request) -> Response:
        """
        Calcula y retorna la carga y pacientes atendidos o tickets emitidos por personal en una jornada.
        Parámetro opcional: ?fecha=YYYY-MM-DD
        Permiso exclusivo: Admin y Jefa.
        """
        fecha = validar_formato_fecha(request.query_params.get('fecha'))
        datos = TicketService.obtener_rendimiento_personal(fecha_consulta=fecha)
        return Response(datos, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=['get'],
        url_path='resumen-estudios',
        permission_classes=[IsAuthenticated, IsJefaRole]
    )
    def resumen_estudios(self, request: Request) -> Response:
        """
        Retorna la cantidad de cada estudio médico realizado en la jornada.
        Parámetros opcionales: ?fecha=YYYY-MM-DD, ?search=..., ?top=5
        Permiso exclusivo: Admin y Jefa.
        """
        fecha = validar_formato_fecha(request.query_params.get('fecha'))
        search = request.query_params.get('search')
        top = request.query_params.get('top')
        datos = TicketService.obtener_resumen_estudios(
            fecha_consulta=fecha,
            search=search,
            top=top
        )
        return Response(datos, status=status.HTTP_200_OK)


app_name = 'tickets_endpoints'

router = DefaultRouter()
router.register(r'', TicketViewSet, basename='tickets')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'TicketViewSet',
    'router',
    'urlpatterns',
]
