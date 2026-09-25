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

    def _is_host_allowed(self, host: str) -> bool:
        if '*' in self.allowed_hosts:
            return True
        for pattern in self.allowed_hosts:
            if pattern == host:
                return True
            if pattern.startswith('.') and (host == pattern[1:] or host.endswith(pattern)):
                return True
        return False

    def __call__(self, request: HttpRequest) -> HttpResponse:
        host = request.get_host().split(':')[0]
        if not self._is_host_allowed(host):
            logger.warning(f"Host no confiable detectado: {host}")
            return HttpResponseBadRequest("Disallowed host header.")

        return self.get_response(request)
