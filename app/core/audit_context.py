"""
Variables de contexto y resolución de red para auditoría operacional (SGTP).
Ubicado en core para evitar ciclos de importación entre middlewares y servicios.
"""
from typing import Tuple
from contextvars import ContextVar
from django.conf import settings
from django.http import HttpRequest

audit_client_ip: ContextVar[str] = ContextVar('audit_client_ip', default='127.0.0.1')
audit_ip_chain: ContextVar[str] = ContextVar('audit_ip_chain', default='')
audit_ip_trusted: ContextVar[bool] = ContextVar('audit_ip_trusted', default=True)
audit_user_agent: ContextVar[str] = ContextVar('audit_user_agent', default='')
audit_device_summary: ContextVar[str] = ContextVar('audit_device_summary', default='')


def resolver_ip_cliente(request: HttpRequest) -> Tuple[str, str, bool]:
    """
    Determina la dirección IP del cliente a través de la cadena de proxies inversos (Vercel -> Render -> Daphne/Django).
    Calcula desde la derecha según settings.AUDITORIA_PROXY_HOPS (por defecto 2).
    Retorna: (ip_resuelta, cadena_cruda, es_confiable)
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    cadena_cruda = x_forwarded_for.strip() if x_forwarded_for else ''
    hops_configurados = getattr(settings, 'AUDITORIA_PROXY_HOPS', 2)

    if not cadena_cruda:
        remote_addr = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return remote_addr, remote_addr, True

    partes = [p.strip() for p in cadena_cruda.split(',') if p.strip()]
    if not partes:
        remote_addr = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return remote_addr, cadena_cruda, False

    if len(partes) >= hops_configurados:
        ip_cliente = partes[-hops_configurados]
        es_confiable = True
    else:
        ip_cliente = partes[0]
        es_confiable = False

    return ip_cliente, cadena_cruda, es_confiable


def sintetizar_dispositivo(user_agent: str) -> str:
    """Extrae un resumen legible de navegador y sistema operativo a partir del User-Agent."""
    if not user_agent:
        return "Desconocido"

    ua = user_agent

    navegador = "Navegador"
    if "Edg/" in ua or "Edge/" in ua:
        navegador = "Edge"
    elif "Chrome/" in ua and "Chromium/" not in ua:
        navegador = "Chrome"
    elif "Firefox/" in ua:
        navegador = "Firefox"
    elif "Safari/" in ua and "Chrome/" not in ua:
        navegador = "Safari"
    elif "Opera/" in ua or "OPR/" in ua:
        navegador = "Opera"

    sistema = "Desconocido"
    if "Windows NT 10.0" in ua:
        sistema = "Windows 10/11"
    elif "Windows NT 6.3" in ua:
        sistema = "Windows 8.1"
    elif "Windows NT 6.1" in ua:
        sistema = "Windows 7"
    elif "Windows" in ua:
        sistema = "Windows"
    elif "Mac OS X" in ua:
        sistema = "macOS"
    elif "Android" in ua:
        sistema = "Android"
    elif "iPhone" in ua or "iPad" in ua:
        sistema = "iOS"
    elif "Linux" in ua:
        sistema = "Linux"

    return f"{navegador} · {sistema}"

