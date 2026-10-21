"""
ASGI config for SGTP Backend project.
Permite enrutar tráfico HTTP estándar y conexiones WebSocket de Django Channels.
"""
import os
from django.core.asgi import get_asgi_application
from django.conf import settings # Importamos settings para leer los orígenes permitidos desde base.py

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

# Inicializar Django ASGI antes de importar consumers y routing
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from channels.auth import AuthMiddlewareStack
from app.routing import websocket_urlpatterns

# Importamos tu middleware personalizado para leer el ?token=
from app.middlewares.ws_auth import QueryStringAuthMiddleware 

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": OriginValidator(
        QueryStringAuthMiddleware(
            AuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
        allowed_origins=settings.CORS_ALLOWED_ORIGINS # Valida contra los dominios en base.py
    ),
})

app = application
