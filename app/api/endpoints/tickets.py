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
from rest_framework.exceptions import ValidationError

from app.core.permissions import IsJefaRole
from app.core.validators import validar_formato_fecha
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    EstadoTicket,
)
from app.models.user import RolPersonal
from app.models.studies import Estudios
from app.schemas.ticket import (
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketHistorialDetailSerializer,
)
from app.services.ticket_service import TicketService
from app.services.audit_service import AuditService
from app.models.audit import AccionAuditoria, ResultadoAuditoria
from app.services.triage_service import construir_orden_prioridad_case

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def notificar_eventos_ticket(ticket_instance, accion='NEW_TICKET'):
    """
    Notifica a varios consumidores (Jefa, Pantallas de Espera, Boxes, Reportes)
    sobre la creación o cambio de un ticket.
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    data = TicketDetailSerializer(ticket_instance).data
    payload_ticket = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'TICKET_CREATED',
            'action': accion,
            'data': data
        }
    }
    payload_queue = {
        'type': 'broadcast_event',
        'payload': {
            'event': 'QUEUE_UPDATED',
            'action': 'TICKET_CREATED',
            'data': data
        }
    }

    # 1. Notificar al panel de la Jefa (Monitor Operativo)
    async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload_ticket)

    # 2. Notificar a las Pantallas de Sala de Espera / Cola Multibox (ambos eventos)
    async_to_sync(channel_layer.group_send)('sgtp_queue_live', payload_queue)
    async_to_sync(channel_layer.group_send)('sgtp_queue_live', payload_ticket)

    # 3. Notificar a los Técnicos / Admisión (Últimos ingresos)
    async_to_sync(channel_layer.group_send)('sgtp_tickets_live', payload_ticket)

    # 4. Notificar a la vista de Reportes (Secretaría / Jefa)
    async_to_sync(channel_layer.group_send)('sgtp_reports_live', payload_ticket)


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

    def get_queryset(self):
        qs = super().get_queryset().filter(is_deleted=False)
        if self.action == 'list':
            por_atender = self.request.query_params.get('por_atender')
            es_rol_box = getattr(self.request.user, 'rol', None) == RolPersonal.BOX
            if por_atender in ('true', '1', 'True') or es_rol_box:
                qs = qs.filter(estado__in=[EstadoTicket.PENDIENTE, EstadoTicket.EN_ATENCION])
            else:
                estado_param = self.request.query_params.get('estado')
                if estado_param:
                    estados = [e.strip() for e in estado_param.split(',') if e.strip()]
                    if estados:
                        qs = qs.filter(estado__in=estados)
        return qs

    def get_permissions(self):
        if self.action in ['rendimiento_personal', 'resumen_estudios', 'tickets_por_personal']:
            return [IsAuthenticated(), IsJefaRole()]
        return super().get_permissions()

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

        # Si la lista está vacía (no mandaron estudios), cortamos la ejecución y devolvemos error 400
        if not estudios_ids:
            raise ValidationError({
                "detail": "No se puede admitir a un paciente ni crear un ticket sin seleccionar al menos un estudio."
            })

        estudios_ids = serializer.validated_data.pop('estudios_ids', [])
        ticket = serializer.save(personal_admision=self.request.user)

        # Asociar estudios seleccionados
        if estudios_ids:
            estudios_queryset = list(Estudios.objects.filter(id__in=estudios_ids, activo=True))
            for estudio in estudios_queryset:
                TicketEstudios.objects.create(ticket=ticket, estudio=estudio)






    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        ticket = serializer.instance

        # Notificar al WebSocket la creación del ticket (Cola, Boxes, Jefatura y Reportes)
        notificar_eventos_ticket(ticket, 'NEW_TICKET')

        AuditService.registrar_evento(
            accion=AccionAuditoria.TICKET_CREADO,
            usuario=request.user,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Emisión de Ticket {ticket.num_totem} ({ticket.clasificacion_triage})',
            entidad_tipo='Ticket',
            entidad_id=ticket.pk,
            metadata={
                'ticket': ticket.num_totem,
                'triage': ticket.clasificacion_triage,
                'paciente_id': ticket.paciente_id,
            },
            request=request
        )

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

        AuditService.registrar_evento(
            accion=AccionAuditoria.TICKET_EDITADO,
            usuario=request.user,
            resultado=ResultadoAuditoria.EXITO,
            descripcion=f'Modificación de Ticket {ticket_modificado.num_totem}',
            entidad_tipo='Ticket',
            entidad_id=ticket_modificado.pk,
            metadata={
                'ticket': ticket_modificado.num_totem,
                'estado': ticket_modificado.estado,
            },
            request=request
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

    @action(
        detail=False,
        methods=['get'],
        url_path=r'personal/(?P<personal_id>\d+)',
        permission_classes=[IsAuthenticated, IsJefaRole]
    )
    def tickets_por_personal(self, request: Request, personal_id: str = None) -> Response:
        """
        Retorna los tickets asistenciales emitidos o atendidos por un integrante del personal.
        Parámetros opcionales: ?fecha=YYYY-MM-DD, ?tipo=admision|box
        Permiso exclusivo: Admin y Jefa.
        """
        pid = personal_id or request.query_params.get('personal_id')
        if not pid:
            return Response(
                {"detail": "Debe especificar el identificador del personal."},
                status=status.HTTP_400_BAD_REQUEST
            )
        fecha = validar_formato_fecha(request.query_params.get('fecha'))
        tipo = request.query_params.get('tipo')
        try:
            datos = TicketService.obtener_tickets_por_personal(
                personal_id=int(pid),
                fecha_consulta=fecha,
                tipo=tipo
            )
            return Response(datos, status=status.HTTP_200_OK)
        except Exception as e:
            from django.core.exceptions import ObjectDoesNotExist
            if isinstance(e, ObjectDoesNotExist):
                return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
            raise e


app_name = 'tickets_endpoints'

router = DefaultRouter()
router.register(r'', TicketViewSet, basename='tickets')

urlpatterns = [
    path(
        'personal/<int:personal_id>/',
        TicketViewSet.as_view({'get': 'tickets_por_personal'}, permission_classes=[IsAuthenticated, IsJefaRole]),
        name='tickets-por-personal'
    ),
    path('', include(router.urls)),
]

__all__ = [
    'TicketViewSet',
    'router',
    'urlpatterns',
]
