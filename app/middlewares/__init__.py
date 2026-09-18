"""
Módulo de Middlewares de la Aplicación SGTP.
"""
from app.middlewares.logging import RequestLoggingMiddleware
from app.middlewares.trusted_hosts import TrustedHostsMiddleware
from app.middlewares.error_handler import GlobalErrorHandlerMiddleware
from app.middlewares.security import JWEDecryptionMiddleware, ShiftScheduleRestrictionMiddleware

__all__ = [
    'RequestLoggingMiddleware',
    'TrustedHostsMiddleware',
    'GlobalErrorHandlerMiddleware',
    'JWEDecryptionMiddleware',
    'ShiftScheduleRestrictionMiddleware',
]
