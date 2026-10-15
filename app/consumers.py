import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

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
