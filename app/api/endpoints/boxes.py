"""
Controlador de Endpoints para Gestión y Operativa de Boxes de Atención.
"""
from django.urls import path, include
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
    MotivoCierreBox,
)
from app.models.user import RolPersonal
from app.schemas.box import (
    BoxSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
    ModificarEstudiosBoxSerializer,
)
from app.schemas.ticket import TicketDetailSerializer, TicketHistorialDetailSerializer
from app.models.ticket import Ticket
from app.services.triage_service import TriageService
from app.services.audit_service import AuditService
from app.models.audit import AccionAuditoria, ResultadoAuditoria
from app.core.permissions import IsBoxOrJefa
from app.services.ticket_service import TicketService


def notificar_actualizacion_reportes():
    """
    Obliga a las vistas de Reportes (Secretaría / Jefa) a actualizarse
    cuando ocurre un evento significativo (ej. cierre de atención).
    """
    channel_layer = get_channel_layer()
    payload = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'REFRESH_REPORTS',
            'action': 'REFRESH_REPORTS',
            'mensaje': 'Nuevos datos estadísticos disponibles'
        }
    }
    async_to_sync(channel_layer.group_send)('sgtp_reports_live', payload)
    async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)


def notificar_monitor_operativo_box(box_instance):
    """
    Emite al WebSocket tanto a Jefatura como a Boxes en línea.
    """
    channel_layer = get_channel_layer()
    payload = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'BOX_UPDATED',
            'action': 'UPDATE_BOX',
            'data': BoxSerializer(box_instance).data
        }
    }
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
        user = self.request.user
        instance = serializer.instance
        nuevo_estado = serializer.validated_data.get('estado', instance.estado if instance else None)
        estado_anterior = instance.estado if instance else None

        es_rol_box = (
            user.is_authenticated
            and getattr(user, 'rol', None) == RolPersonal.BOX
            and not getattr(user, 'is_superuser', False)
        )

        if es_rol_box and 'estado' in serializer.validated_data:
            if (
                estado_anterior == EstadoBox.FUERA_DE_SERVICIO
                or nuevo_estado == EstadoBox.FUERA_DE_SERVICIO
            ) and nuevo_estado != estado_anterior:
                raise PermissionDenied(
                    "Solo la Jefa de Laboratorio puede habilitar o poner fuera de servicio un box."
                )

        box = serializer.save()

        # Si un técnico pone el box en disponible y no tenía personal asignado, vincularlo liberando otros boxes
        if box.estado == EstadoBox.DISPONIBLE and es_rol_box:
            Box.objects.filter(personal_actual=user).exclude(pk=box.pk).update(personal_actual=None)
            if box.personal_actual != user:
                box.personal_actual = user
                box.save(update_fields=['personal_actual'])

        # Notificar al WebSocket sobre el cambio de estado
        notificar_monitor_operativo_box(box)

    @action(detail=True, methods=['post'], url_path='tomar-box', permission_classes=[IsBoxOrJefa])
    def tomar_box(self, request: Request, pk: str = None) -> Response:
        """
        Asigna inmediatamente al técnico solicitante al box físico seleccionado,
        liberando cualquier otro box previo para garantizar exclusividad 1 a 1.
        Si el box se encuentra 'Fuera de servicio', conserva dicho estado hasta que la Jefa lo habilite.
        """
        box = self.get_object()
        personal = request.user

        # Liberar al personal de cualquier otro box previo y notificar a WS
        boxes_previos = list(Box.objects.filter(personal_actual=personal).exclude(pk=box.pk))
        if boxes_previos:
            Box.objects.filter(personal_actual=personal).exclude(pk=box.pk).update(personal_actual=None)
            for b_prev in boxes_previos:
                b_prev.personal_actual = None
                notificar_monitor_operativo_box(b_prev)

        box.personal_actual = personal
        box.save(update_fields=['personal_actual'])

        # Notificar al WebSocket que un técnico se posicionó en el box
        notificar_monitor_operativo_box(box)

        AuditService.registrar_evento(
            accion=AccionAuditoria.BOX_TOMADO,
            usuario=personal,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Toma de posesión de Box {box.numero}',
            entidad_tipo='Box',
            entidad_id=box.numero,
            metadata={'box': f'Box {box.numero}'},
            request=request
        )

        return Response(BoxSerializer(box).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='llamar-siguiente', permission_classes=[IsBoxOrJefa])
    def llamar_siguiente(self, request: Request, pk: str = None) -> Response:
        """
        Llama al siguiente paciente disponible según el algoritmo multibox,
        o convoca directamente a un paciente específico si se envía 'ticket_id' (ignorando triage).
        Box 1 prioriza Discapacidad; Boxes 2..N excluyen Discapacidad.
        Ejecución atómica con select_for_update(skip_locked=True).
        """
        box = self.get_object()
        ticket_id = request.data.get('ticket_id') if isinstance(request.data, dict) else None

        try:
            ticket, asignacion = TriageService.llamar_siguiente_paciente(
                box_id=box.id,
                personal=request.user,
                ticket_id=ticket_id
            )
        except DjangoValidationError as e:
            detail_msg = e.messages[0] if hasattr(e, 'messages') and e.messages else str(e)
            return Response({"detail": detail_msg}, status=status.HTTP_400_BAD_REQUEST)

        if not ticket:
            return Response(
                {
                    "mensaje": "No hay pacientes en cola de espera pendientes de atención para este Box.",
                    "box": BoxSerializer(box).data,
                    "ticket": None
                },
                status=status.HTTP_200_OK
            )

        # Notificamos a la cola de espera y al monitor de jefatura que este ticket ya fue llamado
        channel_layer = get_channel_layer()
        llamado_payload = {
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
        async_to_sync(channel_layer.group_send)('sgtp_queue_live', llamado_payload)
        async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', llamado_payload)

        # Notificamos a boxes y monitoreo que el box ahora está en atención
        box.refresh_from_db()
        notificar_monitor_operativo_box(box)
        notificar_actualizacion_reportes()

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

        AuditService.registrar_evento(
            accion=AccionAuditoria.ESTUDIOS_MODIFICADOS,
            usuario=request.user,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Modificación de estudios en Box {box.numero} para Ticket {ticket.num_totem}',
            entidad_tipo='Ticket',
            entidad_id=ticket.pk,
            metadata={
                'ticket': ticket.num_totem,
                'box': f'Box {box.numero}',
                'estudios_cancelados': len(serializer.validated_data.get('cancelar_estudios', [])),
                'estudios_agregados': len(serializer.validated_data.get('agregar_estudios', []))
            },
            request=request
        )

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
        Finaliza o cancela la atención en curso en el Box y lo deja en estado 'Disponible'.
        """
        box = self.get_object()
        serializer = CerrarAtencionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        motivo_cierre = serializer.validated_data.get('motivo_cierre', MotivoCierreBox.FINALIZADO)
        observaciones_cierre = serializer.validated_data.get('observaciones_cierre', '')

        try:
            asignacion = TriageService.cerrar_atencion(
                box_id=box.id,
                personal=request.user,
                motivo_cierre=motivo_cierre,
                observaciones_cierre=observaciones_cierre
            )
        except DjangoValidationError as e:
            detail_msg = e.messages[0] if hasattr(e, 'messages') and e.messages else str(e)
            return Response({"detail": detail_msg}, status=status.HTTP_400_BAD_REQUEST)

        # Refrescar box
        box.refresh_from_db()

        # Notificar al WebSocket que el box volvió a estar disponible
        notificar_monitor_operativo_box(box)
        # Notifica a Secretaría/Jefa que las estadísticas (Atendidos, Cancelados, Espera Promedio) cambiaron
        notificar_actualizacion_reportes()
        # Si fue atención finalizada (no cancelada por ausencia), notificar estudios de laboratorio
        if motivo_cierre != MotivoCierreBox.CANCELADO:
            notificar_actualizacion_estudios_laboratorio(ticket=getattr(asignacion, 'ticket', None))

        es_cancelado = motivo_cierre == MotivoCierreBox.CANCELADO
        mensaje_respuesta = (
            f"Turno cancelado por ausencia del paciente en Box {box.numero}. El box se encuentra disponible."
            if es_cancelado
            else f"Atención del Box {box.numero} finalizada."
        )

        ticket_data = None
        if asignacion and asignacion.ticket:
            ticket_instancia = Ticket.objects.select_related(
                'paciente', 'personal_admision', 'box_actual'
            ).prefetch_related(
                'estudios__estudio',
                'asignaciones_historial__personal',
                'asignaciones_historial__box'
            ).filter(pk=asignacion.ticket.pk).first()
            if ticket_instancia:
                ticket_data = TicketHistorialDetailSerializer(ticket_instancia).data

        return Response(
            {
                "mensaje": mensaje_respuesta,
                "box": BoxSerializer(box).data,
                "asignacion": AsignacionesBoxSerializer(asignacion).data,
                "ticket": ticket_data
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
