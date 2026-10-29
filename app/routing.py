from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Existentes
    re_path(r'^ws/tickets/?$', consumers.TicketEventsConsumer.as_asgi()),
    re_path(r'^ws/boxes/?$', consumers.BoxStatusConsumer.as_asgi()),
    
    # Nuevos para el Sistema de Gestión de Triage y Flujo de Pacientes
    re_path(r'^ws/queue/?$', consumers.QueueEventsConsumer.as_asgi()),
    re_path(r'^ws/laboratorio/?$', consumers.LabResultsConsumer.as_asgi()),
    re_path(r'^ws/reportes/?$', consumers.ReportsConsumer.as_asgi()),
    
    # Monitor Operativo (Jefatura)
    re_path(r'^ws/monitor-operativo/?$', consumers.MonitorOperativoConsumer.as_asgi()),

    # NUEVA RUTA: Auditoría Operacional y Actividad en Vivo (Jefa y Admin)
    re_path(r'^ws/auditoria/?$', consumers.AuditoriaEventsConsumer.as_asgi()),
]
