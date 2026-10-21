"""
ASGI config for SGTP Backend project.
Permite enrutar tráfico HTTP estándar y conexiones WebSocket de Django Channels.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

# Inicializar Django ASGI antes de importar consumers y routing
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.auth import AuthMiddlewareStack
from app.routing import websocket_urlpatterns

from app.middlewares.ws_auth import QueryStringAuthMiddleware

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        QueryStringAuthMiddleware(
            AuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        )
    ),
})

CORS_ALLOWED_ORIGINS = [
    "https://sgtp-develop.vercel.app",
    "http://localhost:5173", # Para desarrollo local
]

CSRF_TRUSTED_ORIGINS = [
    "https://sgtp-develop.vercel.app",
]

app = application
        )
    ),
})

app = application
