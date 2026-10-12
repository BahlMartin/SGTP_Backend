"""
Clases personalizadas de autenticación para SGTP API.
Proporciona soporte para sesiones desacopladas de SPA (Vercel) sin conflicto de tokens CSRF.
"""
from rest_framework.authentication import SessionAuthentication
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Autenticación por sesión de Django exenta de validación estricta de token CSRF
    para endpoints de API REST consumidos por aplicaciones frontend desacopladas (SPA).
    """

    def enforce_csrf(self, request) -> None:
        # Omite la verificación estricta de CSRF en llamadas REST API
        return


class CsrfExemptSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    """
    Esquema OpenAPI para drf-spectacular que documenta CsrfExemptSessionAuthentication
    como autenticación basada en Cookie de Sesión (sessionid).
    """
    target_class = 'app.core.authentication.CsrfExemptSessionAuthentication'
    name = 'SessionCookieAuth'

    def get_security_requirement(self, auto_schema):
        return {self.name: []}

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'sessionid',
            'description': 'Autenticación por cookie de sesión estándar de Django (sessionid).'
        }


__all__ = [
    'CsrfExemptSessionAuthentication',
    'CsrfExemptSessionAuthenticationScheme',
]
