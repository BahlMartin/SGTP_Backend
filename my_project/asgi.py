import os
from django.core.asgi import get_asgi_application
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from channels.auth import AuthMiddlewareStack
from app.routing import websocket_urlpatterns
from app.middlewares.ws_auth import QueryStringAuthMiddleware 

# Lista explicita de orígenes permitidos para WebSockets
ALLOWED_WS_ORIGINS = [
    "https://sgtp-develop.vercel.app",
    "https://sgtp-frontend-backend.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": OriginValidator(
        QueryStringAuthMiddleware(
            AuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
        allowed_origins=ALLOWED_WS_ORIGINS  # Se asegura de incluir el dominio de Vercel
    ),
})

app = application
