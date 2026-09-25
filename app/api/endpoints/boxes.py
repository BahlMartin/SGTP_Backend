"""
Controlador de Endpoints para Gestión y Operativa de Boxes de Atención.
"""
from django.urls import path, include
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from app.models.box import (
    Box,
    AsignacionesBox,
)
from app.schemas.box import (
    BoxSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
)
from app.schemas.ticket import TicketDetailSerializer
from app.services.triage_service import TriageService
from app.core.permissions import IsBoxOrJefa


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


class AsignacionesBoxViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Historial inmutable de asignaciones y atenciones en Box.
    """
    queryset = AsignacionesBox.objects.all().select_related('box', 'personal', 'ticket').order_by('-fecha_hora_inicio')
    serializer_class = AsignacionesBoxSerializer
    permission_classes = [IsAuthenticated]


app_name = 'boxes_endpoints'

router = DefaultRouter()
router.register(r'asignaciones', AsignacionesBoxViewSet, basename='asignaciones')
router.register(r'', BoxViewSet, basename='boxes')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'BoxViewSet',
    'AsignacionesBoxViewSet',
    'router',
    'urlpatterns',
]
