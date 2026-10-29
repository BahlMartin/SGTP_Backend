"""
Middleware para registrar peticiones HTTP (logs de auditoría y rendimiento).
Registra método, ruta, IP del cliente, código de respuesta y tiempo de ejecución.
"""
import time
import logging
from typing import Callable
from django.http import HttpRequest, HttpResponse
from app.middlewares.audit_context import resolver_ip_cliente

logger = logging.getLogger('sgtp.requests')


class RequestLoggingMiddleware:
    """Middleware para interceptar y registrar métricas de cada petición entrante."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.time()

        # Obtener IP del cliente confiable según saltos de proxy
        client_ip, cadena, confiable = resolver_ip_cliente(request)

        response = self.get_response(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        user_info = getattr(request, 'user', 'Anonymous')
        conf_str = "OK" if confiable else "UNTRUSTED"

        logger.info(
            f"[{request.method}] {request.path} -> {response.status_code} "
            f"({duration_ms}ms) | IP: {client_ip} ({conf_str}) | User: {user_info}"
        )

        return response
