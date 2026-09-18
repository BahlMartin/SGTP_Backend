"""
Middleware para registrar peticiones HTTP (logs de auditoría y rendimiento).
Registra método, ruta, IP del cliente, código de respuesta y tiempo de ejecución.
"""
import time
import logging
from typing import Callable
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger('sgtp.requests')


class RequestLoggingMiddleware:
    """Middleware para interceptar y registrar métricas de cada petición entrante."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.time()

        # Obtener IP del cliente
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            client_ip = x_forwarded_for.split(',')[0].strip()
        else:
            client_ip = request.META.get('REMOTE_ADDR', 'unknown')

        response = self.get_response(request)

        duration_ms = round((time.time() - start_time) * 1000, 2)
        user_info = getattr(request, 'user', 'Anonymous')

        logger.info(
            f"[{request.method}] {request.path} -> {response.status_code} "
            f"({duration_ms}ms) | IP: {client_ip} | User: {user_info}"
        )

        return response
