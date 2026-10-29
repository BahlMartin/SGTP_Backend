import json
import logging
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from app.models.user import RolPersonal
from app.middlewares.ws_auth import get_user_from_session

logger = logging.getLogger('app.consumers')


class BaseHospitalConsumer(AsyncWebsocketConsumer):
    """
    Consumidor base con soporte de autenticación por mensaje inicial (In-Band Auth),
    parseo JSON y manejo seguro de grupos Channels.
    """
    group_name = None
    is_authenticated = False

    async def connect(self):
        if self.group_name:
            await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"[WebSocket] Conectado: {self.__class__.__name__} ({self.channel_name})")

    async def disconnect(self, close_code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"[WebSocket] Desconectado: {self.__class__.__name__} código={close_code}")

    async def broadcast_event(self, event):
        """
        Handler genérico para enviar mensajes transmitidos por el group_send de Channel Layer.
        """
        payload = event.get('payload', {})
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    async def receive(self, text_data=None, bytes_data=None):
        """
        Procesa mensajes entrantes desde el cliente:
        - Ping / Pong
        - Autenticación In-Band ({ type: 'AUTH', token: '...' })
        """
        try:
            data = json.loads(text_data) if text_data else {}
            msg_type = data.get('type')

            if msg_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong', 'timestamp': data.get('timestamp')}))
                return

            if msg_type == 'AUTH':
                token = data.get('token')
                user = await get_user_from_session(token) if token else None
                if user and user.is_authenticated:
                    self.scope['user'] = user
                    self.is_authenticated = True
                    await self.on_authenticated(user)
                    await self.send(text_data=json.dumps({
                        'type': 'AUTH_SUCCESS',
                        'email': getattr(user, 'email', ''),
                        'rol': getattr(user, 'rol', '')
                    }))
                else:
                    await self.send(text_data=json.dumps({
                        'type': 'AUTH_ERROR',
                        'detail': 'Sesión inválida o expirada'
                    }))
                    await self.on_auth_failed()
                return

        except Exception as e:
            logger.warning(f"[{self.__class__.__name__}] Error procesando mensaje: {e}")

    async def on_authenticated(self, user):
        """Hook opcional para consumidores que requieran acciones post-autenticación."""
        pass

    async def on_auth_failed(self):
        """Hook opcional cuando la autenticación falla."""
        pass


class TicketEventsConsumer(BaseHospitalConsumer):
    """
    Transmite en tiempo real eventos del ciclo de vida de tickets y triage:
    - Creación de ticket
    - Llamados a box
    - Cambios de estado (Espera, Atención, Completado, Cancelado)
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_tickets_live'


class BoxStatusConsumer(BaseHospitalConsumer):
    """
    Transmite en tiempo real el estado de los boxes hospitalarios:
    - Ocupado / Libre
    - Paciente en atención
    - Conexión y desconexión de técnicos
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_boxes_live'


class QueueEventsConsumer(BaseHospitalConsumer):
    """
    Transmite la cola multibox centralizada.
    Ideal para las pantallas de las salas de espera.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_queue_live'


class LabResultsConsumer(BaseHospitalConsumer):
    """
    Transmite alertas de estudios de laboratorio (completados, críticos, etc.).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_lab_live'


class ReportsConsumer(BaseHospitalConsumer):
    """
    Transmite métricas y reportes en tiempo real para el dashboard administrativo.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_reports_live'


class MonitorOperativoConsumer(BaseHospitalConsumer):
    """
    Transmite métricas globales en tiempo real para el panel 
    de Monitoreo Operativo (Jefa y Admin).
    Protegido con Autenticación In-Band (por mensaje inicial).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_monitor_operativo'
        self.auth_timeout_task = None
        self.is_authenticated = False

    @database_sync_to_async
    def _has_jefa_permission(self, user):
        """Replicamos la lógica de IsJefaRole de forma asíncrona"""
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA])

    async def connect(self):
        # 1. Aceptamos la conexión preliminarmente para permitir al cliente identificarse por mensaje
        await self.accept()
        logger.info(f"[WebSocket] MonitorOperativo: Conexión abierta, esperando AUTH ({self.channel_name})")

        # 2. Si ya viniese autenticado por cookie (ej. desarrollo local)
        user = self.scope.get('user')
        if await self._has_jefa_permission(user):
            self.is_authenticated = True
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.send(text_data=json.dumps({
                'type': 'AUTH_SUCCESS',
                'email': getattr(user, 'email', ''),
                'rol': getattr(user, 'rol', '')
            }))
            return

        # 3. Timeout de 5 segundos: si el cliente no envía { type: 'AUTH' }, cerrar con 4003
        self.auth_timeout_task = asyncio.create_task(self._wait_for_auth())

    async def _wait_for_auth(self):
        try:
            await asyncio.sleep(5)
            if not self.is_authenticated:
                logger.warning(f"[WebSocket] MonitorOperativo: Timeout de autenticación agotado ({self.channel_name})")
                await self.send(text_data=json.dumps({
                    'type': 'AUTH_ERROR',
                    'detail': 'Tiempo de espera de autenticación agotado'
                }))
                await self.close(code=4003)
        except asyncio.CancelledError:
            pass

    async def on_authenticated(self, user):
        if self.auth_timeout_task and not self.auth_timeout_task.done():
            self.auth_timeout_task.cancel()

        if await self._has_jefa_permission(user):
            self.is_authenticated = True
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            logger.info(f"[WebSocket] MonitorOperativo: Usuario {user.email} (rol: {user.rol}) autorizado.")
        else:
            logger.warning(f"[WebSocket] MonitorOperativo: Usuario {user.email} sin permisos suficientes (rol: {user.rol}).")
            await self.send(text_data=json.dumps({
                'type': 'AUTH_ERROR',
                'detail': 'Acceso denegado. Se requiere rol Jefa o Admin.'
            }))
            await self.close(code=4003)

    async def on_auth_failed(self):
        if self.auth_timeout_task and not self.auth_timeout_task.done():
            self.auth_timeout_task.cancel()
        await self.close(code=4003)

    async def disconnect(self, close_code):
        if self.auth_timeout_task and not self.auth_timeout_task.done():
            self.auth_timeout_task.cancel()
        if self.is_authenticated and self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"[WebSocket] Desconectado: {self.__class__.__name__} código={close_code}")
