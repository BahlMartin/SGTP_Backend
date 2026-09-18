"""
Módulo Core: Configuración global, base de datos y seguridad.
"""
from app.core.config import settings
from app.core.security import (
    encrypt_jwe,
    decrypt_jwe,
    get_fernet_cipher,
    hash_password,
    verify_password,
)

__all__ = [
    'settings',
    'encrypt_jwe',
    'decrypt_jwe',
    'get_fernet_cipher',
    'hash_password',
    'verify_password',
]
