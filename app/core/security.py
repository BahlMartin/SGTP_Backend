"""
Módulo de Seguridad, Criptografía y Manejo de Tokens/Contraseñas.
Incluye:
- Hashing y verificación de contraseñas con Argon2 / PBKDF2.
- Cifrado a nivel de campo con Fernet.
- Cifrado de payloads con JWE (RFC 7516 A256GCM).
"""
import json
import base64
import hashlib
from typing import Any, Dict
from cryptography.fernet import Fernet
from jwcrypto import jwk, jwe
from django.contrib.auth.hashers import make_password, check_password
from app.core.config import settings


# ==============================================================================
# 1. HASHING Y VERIFICACIÓN DE CONTRASEÑAS
# ==============================================================================
def hash_password(plain_password: str) -> str:
    """Genera un hash seguro usando Argon2 / PBKDF2 configurado en Django."""
    return make_password(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si una contraseña en texto plano coincide con el hash."""
    return check_password(plain_password, hashed_password)


# ==============================================================================
# 2. CRIPTOGRAFÍA SIMÉTRICA (FERNET - FIELD LEVEL ENCRYPTION)
# ==============================================================================
def get_fernet_cipher() -> Fernet:
    """Obtiene una instancia de Fernet inicializada con FERNET_ENCRYPTION_KEY."""
    key = settings.FERNET_ENCRYPTION_KEY
    if not key:
        raise ValueError("FERNET_ENCRYPTION_KEY no está configurada en las variables de entorno.")
    return Fernet(key.encode('utf-8'))


# ==============================================================================
# 3. CRIPTOGRAFÍA DE PAYLOAD JWE (RFC 7516 - A256GCM)
# ==============================================================================
def get_jwe_key() -> jwk.JWK:
    """Obtiene la clave simétrica JWK a partir de JWE_SECRET_KEY."""
    raw_key = settings.JWE_SECRET_KEY
    if not raw_key:
        raise ValueError("JWE_SECRET_KEY no está definida en las variables de entorno.")

    key_bytes = raw_key.encode('utf-8')
    if len(key_bytes) != 32:
        key_bytes = hashlib.sha256(key_bytes).digest()

    b64_k = base64.urlsafe_b64encode(key_bytes).decode('utf-8').rstrip('=')
    return jwk.JWK(kty='oct', k=b64_k)


def encrypt_jwe(payload_data: Dict[str, Any]) -> str:
    """Cifra un diccionario en un token JWE compacto según RFC 7516."""
    key = get_jwe_key()
    payload_json = json.dumps(payload_data, ensure_ascii=False)
    jwetoken = jwe.JWE(
        plaintext=payload_json.encode('utf-8'),
        protected={'alg': 'dir', 'enc': 'A256GCM'}
    )
    jwetoken.add_recipient(key)
    return jwetoken.serialize(compact=True)


def decrypt_jwe(token_str: str) -> Dict[str, Any]:
    """Desencripta un token JWE compacto y retorna el diccionario original."""
    key = get_jwe_key()
    try:
        jwetoken = jwe.JWE()
        jwetoken.deserialize(token_str, key=key)
        payload_bytes = jwetoken.payload
        return json.loads(payload_bytes.decode('utf-8'))
    except Exception as exc:
        raise ValueError(f"Fallo de desencriptación o autenticación JWE: {exc}") from exc


# Alias para retrocompatibilidad
encrypt_payload_jwe = encrypt_jwe
decrypt_payload_jwe = decrypt_jwe
