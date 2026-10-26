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

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from app.models.box import Box, AsignacionesBox, EstadoBox # Asegúrate de que estén importadas
from app.schemas.box import BoxSerializer # Asegúrate de que esté importado

from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
)
from app.models.user import RolPersonal
from app.schemas.box import (
    BoxSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
    ModificarEstudiosBoxSerializer,
)
from app.schemas.ticket import TicketDetailSerializer
from app.services.triage_service import TriageService
from app.core.permissions import IsBoxOrJefa

from app.services.ticket_service import TicketService # Importamos tu servicio de cálculo

def notificar_actualizacion_reportes():
    """
    Obliga a las vistas de Reportes (Secretaría / Jefa) a actualizarse
    cuando ocurre un evento significativo (ej. cierre de atención).
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'sgtp_reports_live', # El grupo definido en ReportsConsumer
        {
            'type': 'broadcast_event',
            'payload': {
                'event': 'REFRESH_REPORTS',
                'action': 'REFRESH_REPORTS',
                'mensaje': 'Nuevos datos estadísticos disponibles'
            }
        }
    )

# Función auxiliar para emitir al WebSocket tanto a Jefatura como a Boxes en línea
def notificar_monitor_operativo_box(box_instance):
    channel_layer = get_channel_layer()
    payload = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'BOX_UPDATED',
            'action': 'UPDATE_BOX',
            'data': BoxSerializer(box_instance).data
        }
    }
    # Emite a Monitor Operativo (Jefatura) y a Boxes Live (Técnicos)
    async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)
    async_to_sync(channel_layer.group_send)('sgtp_boxes_live', payload)

def notificar_actualizacion_estudios_laboratorio(ticket=None):
    """
    Notifica a Jefatura que los estudios de laboratorio han sido consolidados y finalizados
    tras el cierre de atención en Box (cerrar-atencion), ya que el técnico de box es la
    última persona que decide qué estudios se realizan al paciente.
    """
    channel_layer = get_channel_layer()
    payload = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'LAB_STUDIES_UPDATED',
            'action': 'REFRESH_LAB_STUDIES',
            'ticket_id': str(ticket.id_ticket) if ticket and hasattr(ticket, 'id_ticket') else None
        }
    }
    async_to_sync(channel_layer.group_send)('sgtp_lab_live', payload)
    async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)


class BoxViewSet(viewsets.ModelViewSet):
    """
    Gestión operativa de Boxes de atención asistencial.
    """
    queryset = Box.objects.all().select_related('personal_actual').order_by('numero')
    serializer_class = BoxSerializer
    permission_classes = [IsAuthenticated]
    
    def perform_update(self, serializer):
        box = serializer.save()
        # Si un técnico pone el box en disponible y no tenía personal asignado, vincularlo liberando otros boxes
        if box.estado == EstadoBox.DISPONIBLE and self.request.user.is_authenticated:
            if getattr(self.request.user, 'rol', None) == RolPersonal.BOX:
                Box.objects.filter(personal_actual=self.request.user).exclude(pk=box.pk).update(personal_actual=None)
                if box.personal_actual != self.request.user:
                    box.personal_actual = self.request.user
                    box.save(update_fields=['personal_actual'])
        # Si se pone fuera de servicio, desasignar al personal
        elif box.estado == EstadoBox.FUERA_DE_SERVICIO and box.personal_actual is not None:
            box.personal_actual = None
            box.save(update_fields=['personal_actual'])
        # [NUEVO] Notificar al WebSocket sobre el cambio de estado
        notificar_monitor_operativo_box(box)

    @action(detail=True, methods=['post'], url_path='tomar-box', permission_classes=[IsBoxOrJefa])
    def tomar_box(self, request: Request, pk: str = None) -> Response:
        """
        Asigna inmediatamente al técnico solicitante al box físico seleccionado,
        liberando cualquier otro box previo para garantizar exclusividad 1 a 1.
        """
        box = self.get_object()
        personal = request.user

        # Liberar al personal de cualquier otro box previo
        Box.objects.filter(personal_actual=personal).exclude(pk=box.pk).update(personal_actual=None)

        box.personal_actual = personal
        # Si el box estaba fuera de servicio y el técnico se posiciona en él, pasa a Disponible
        if box.estado == EstadoBox.FUERA_DE_SERVICIO:
            box.estado = EstadoBox.DISPONIBLE
            box.save(update_fields=['personal_actual', 'estado'])
        else:
            box.save(update_fields=['personal_actual'])
        # [NUEVO] Notificar al WebSocket que un técnico tomó el box            
        notificar_monitor_operativo_box(box)
        return Response(BoxSerializer(box).data, status=status.HTTP_200_OK)

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
        
        if ticket:
            # Notificamos a la cola de espera que este ticket ya fue llamado
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'sgtp_queue_live', 
                {
                    'type': 'broadcast_event',
                    'payload': {
                        'event': 'TICKET_LLAMADO',
                        'action': 'TICKET_LLAMADO',
                        'data': {
                            'ticket_id': str(ticket.id_ticket),
                            'box_numero': box.numero,
                            'llamado': ticket.num_totem,
                            'ticket': TicketDetailSerializer(ticket).data
                        }
                    }
                }
            )
            # Notificamos a boxes y monitoreo que el box ahora está en atención
            box.refresh_from_db()
            notificar_monitor_operativo_box(box)

        
        return Response(
            {
                "mensaje": f"Paciente llamado con éxito al Box {box.numero}.",
                "ticket": TicketDetailSerializer(ticket).data,
                "asignacion_id": asignacion.id if asignacion else None
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='modificar-estudios', permission_classes=[IsBoxOrJefa])
    def modificar_estudios(self, request: Request, pk: str = None) -> Response:
        """
        Modifica los estudios de la orden médica durante la atención en Box:
        - Cancela estudios erróneos con motivo y auditoría.
        - Agrega nuevos estudios solicitados.
        """
        box = self.get_object()
        serializer = ModificarEstudiosBoxSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            ticket = TriageService.modificar_estudios_atencion(
                box_id=box.id,
                personal=request.user,
                cancelar_estudios=serializer.validated_data.get('cancelar_estudios', []),
                agregar_estudios=serializer.validated_data.get('agregar_estudios', []),
            )
        except DjangoValidationError as e:
            detail_msg = e.messages[0] if hasattr(e, 'messages') and e.messages else str(e)
            return Response({"detail": detail_msg}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "mensaje": f"Estudios del ticket actualizados correctamente en Box {box.numero}.",
                "ticket": TicketDetailSerializer(ticket).data,
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

        # Notificar al WebSocket que el box volvio a estar disponible
        notificar_monitor_operativo_box(box)
        # Notifica a Secretaría/Jefa que las estadísticas (Atendidos, Espera Promedio) cambiaron
        notificar_actualizacion_reportes()
        # Notifica a Jefa/Laboratorio que los estudios fueron consolidados y finalizados tras la consulta en Box
        notificar_actualizacion_estudios_laboratorio(ticket=getattr(asignacion, 'ticket', None))

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
        boxes = Box.objects.all().select_related('personal_actual').order_by('numero')
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
