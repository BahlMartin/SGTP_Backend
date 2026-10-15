from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/tickets/?$', consumers.TicketEventsConsumer.as_asgi()),
    re_path(r'^ws/boxes/?$', consumers.BoxStatusConsumer.as_asgi()),
]
