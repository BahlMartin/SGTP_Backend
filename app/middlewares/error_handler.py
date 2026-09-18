"""
Middleware para capturar excepciones globales y responder con formato JSON estructurado.
Evita fugas de stack trace en producción y asegura consistencia en el API.
"""
import logging
from typing import Callable
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.conf import settings

logger = logging.getLogger('sgtp.exceptions')


class GlobalErrorHandlerMiddleware:
    """Captura excepciones no manejadas durante el ciclo de vida de la petición."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        try:
            return self.get_response(request)
        except Exception as exc:
            return self.process_exception(request, exc)

    def process_exception(self, request: HttpRequest, exception: Exception) -> JsonResponse:
        logger.exception(f"Excepción global no controlada en {request.path}: {exception}")

        is_debug = getattr(settings, 'DEBUG', False)
        error_payload = {
            "error": "INTERNAL_SERVER_ERROR",
            "detail": "Ha ocurrido un error inesperado al procesar la solicitud.",
        }

        if is_debug:
            error_payload["exception_type"] = exception.__class__.__name__
            error_payload["exception_message"] = str(exception)

        return JsonResponse(error_payload, status=500)
