import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
# Asumiendo la ruta segun tu permissions.py
from app.models.user import RolPersonal 
logger = logging.getLogger('app.consumers')


class BaseHospitalConsumer(AsyncWebsocketConsumer):
    """
    Consumidor base con utilidades de parseo JSON y manejo de grupos Channels.
    """
    group_name = None

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
        await self.send(text_data=json.dumps(payload))


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

    async def receive(self, text_data=None, bytes_data=None):
        """
        Permite recibir pings o solicitudes de suscripción de clientes.
        """
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong', 'timestamp': data.get('timestamp')}))
        except Exception as e:
            logger.warning(f"[TicketEventsConsumer] Mensaje recibido no parseable: {e}")


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

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.warning(f"[BoxStatusConsumer] Error procesando mensaje de entrada: {e}")

class QueueEventsConsumer(BaseHospitalConsumer):
    """
    Transmite la cola multibox centralizada.
    Ideal para las pantallas de las salas de espera.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_queue_live'

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.warning(f"[QueueEventsConsumer] Error: {e}")


class LabResultsConsumer(BaseHospitalConsumer):
    """
    Transmite alertas de estudios de laboratorio (completados, críticos, etc.).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_lab_live'

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.warning(f"[LabResultsConsumer] Error: {e}")


class ReportsConsumer(BaseHospitalConsumer):
    """
    Transmite métricas y reportes en tiempo real para el dashboard administrativo.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_reports_live'

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.warning(f"[ReportsConsumer] Error: {e}")

# Nuevo MonitorOperativoConsumer
class MonitorOperativoConsumer(BaseHospitalConsumer):
    """
    Transmite métricas globales en tiempo real para el panel 
    de Monitoreo Operativo (Jefa y Admin).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.group_name = 'sgtp_monitor_operativo'

    @database_sync_to_async
    def _has_jefa_permission(self, user):
        """Replicamos la lógica de IsJefaRole de forma asíncrona"""
        return bool(user and user.is_authenticated and user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA])

    async def connect(self):
        user = self.scope.get('user')
        
        # 1. Validar si el usuario está autenticado y tiene el rol correcto
        has_permission = await self._has_jefa_permission(user)
        
        if has_permission:
            # 2. Si es Jefa o Admin, aceptamos la conexión usando la lógica base
            await super().connect()
        else:
            # 3. Si no tiene permisos, rechazamos la conexión WebSocket
            logger.warning(f"[WebSocket] Conexión rechazada para usuario: {getattr(user, 'username', 'Anónimo')}")
            await self.close(code=4003) # 4003: Prohibido

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data) if text_data else {}
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception as e:
            logger.warning(f"[MonitorOperativoConsumer] Error: {e}")
