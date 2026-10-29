"""
Middleware para capturar y propagar el contexto de auditoría operacional
utilizando las variables de contexto definidas en app.core.audit_context.
"""
from typing import Callable
from django.http import HttpRequest, HttpResponse

from app.core.audit_context import (
    audit_client_ip,
    audit_ip_chain,
    audit_ip_trusted,
    audit_user_agent,
    audit_device_summary,
    resolver_ip_cliente,
    sintetizar_dispositivo,
)


class AuditContextMiddleware:
    """
    Establece las variables de contexto por request y las limpia al finalizar la respuesta.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        ip_cliente, cadena_cruda, confiable = resolver_ip_cliente(request)
        ua = request.META.get('HTTP_USER_AGENT', '')
        disp = sintetizar_dispositivo(ua)

        t1 = audit_client_ip.set(ip_cliente)
        t2 = audit_ip_chain.set(cadena_cruda)
        t3 = audit_ip_trusted.set(confiable)
        t4 = audit_user_agent.set(ua[:255])
        t5 = audit_device_summary.set(disp[:120])

        try:
            response = self.get_response(request)
            return response
        finally:
            audit_client_ip.reset(t1)
            audit_ip_chain.reset(t2)
            audit_ip_trusted.reset(t3)
            audit_user_agent.reset(t4)
            audit_device_summary.reset(t5)


__all__ = ['AuditContextMiddleware']

