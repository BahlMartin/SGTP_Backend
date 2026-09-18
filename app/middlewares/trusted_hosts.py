"""
Middleware para validar hosts permitidos y mitigar ataques de Host Header Injection.
"""
import logging
from typing import Callable, List
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.conf import settings

logger = logging.getLogger('sgtp.security')


class TrustedHostsMiddleware:
    """Valida que la cabecera Host de la petición coincida con la lista configurada."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.allowed_hosts: List[str] = getattr(settings, 'ALLOWED_HOSTS', ['*'])

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if '*' in self.allowed_hosts:
            return self.get_response(request)

        host = request.get_host().split(':')[0]
        if host not in self.allowed_hosts:
            logger.warning(f"Host no confiable detectado: {host}")
            return HttpResponseBadRequest("Disallowed host header.")

        return self.get_response(request)
