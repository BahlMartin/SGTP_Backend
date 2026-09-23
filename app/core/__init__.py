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
from app.core.validators import (
    validar_solo_letras_min2,
    validar_dni_positivo,
)

__all__ = [
    'settings',
    'encrypt_jwe',
    'decrypt_jwe',
    'get_fernet_cipher',
    'hash_password',
    'verify_password',
    'validar_solo_letras_min2',
    'validar_dni_positivo',
]
