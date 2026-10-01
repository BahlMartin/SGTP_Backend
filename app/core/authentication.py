"""
Clases personalizadas de autenticación para SGTP API.
Proporciona soporte para sesiones desacopladas de SPA (Vercel) sin conflicto de tokens CSRF.
"""
from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """
    Autenticación por sesión de Django exenta de validación estricta de token CSRF
    para endpoints de API REST consumidos por aplicaciones frontend desacopladas (SPA).
    """

    def enforce_csrf(self, request) -> None:
        # Omite la verificación estricta de CSRF en llamadas REST API
        return


__all__ = ['CsrfExemptSessionAuthentication']
