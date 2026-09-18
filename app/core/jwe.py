"""
Utilidad para Cifrado y Descifrado de Payloads con JWE (RFC 7516).
Algoritmo: dir (clave directa) con cifrado autenticado A256GCM.
Todas las claves se resuelven exclusivamente desde settings (cargadas desde .env).
"""
import json
import base64
from typing import Any, Dict
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jwcrypto import jwk, jwe


def get_jwe_key() -> jwk.JWK:
    """
    Obtiene la clave simétrica JWK a partir de JWE_SECRET_KEY en settings/.env.
    """
    raw_key = getattr(settings, 'JWE_SECRET_KEY', None)
    if not raw_key:
        raise ImproperlyConfigured("JWE_SECRET_KEY no está definida en .env ni en settings.")

    key_bytes = raw_key.encode('utf-8')
    # Clave simétrica de 256 bits (32 bytes)
    if len(key_bytes) < 32:
        # Asegurar longitud rellenando con sha256 de la clave
        import hashlib
        key_bytes = hashlib.sha256(key_bytes).digest()
    elif len(key_bytes) > 32:
        import hashlib
        key_bytes = hashlib.sha256(key_bytes).digest()

    b64_k = base64.urlsafe_b64encode(key_bytes).decode('utf-8').rstrip('=')
    return jwk.JWK(kty='oct', k=b64_k)


def encrypt_payload_jwe(payload_data: Dict[str, Any]) -> str:
    """
    Cifra un diccionario en un token JWE compacto según RFC 7516.
    Algoritmo: 'dir', Encriptación: 'A256GCM'.
    """
    key = get_jwe_key()
    payload_json = json.dumps(payload_data, ensure_ascii=False)
    jwetoken = jwe.JWE(
        plaintext=payload_json.encode('utf-8'),
        protected={'alg': 'dir', 'enc': 'A256GCM'}
    )
    jwetoken.add_recipient(key)
    return jwetoken.serialize(compact=True)


def decrypt_payload_jwe(token_str: str) -> Dict[str, Any]:
    """
    Desencripta un token JWE compacto y retorna el diccionario de datos original.
    Lanza ValueError si el token es inválido o no puede ser autenticado.
    """
    key = get_jwe_key()
    try:
        jwetoken = jwe.JWE()
        jwetoken.deserialize(token_str, key=key)
        payload_bytes = jwetoken.payload
        return json.loads(payload_bytes.decode('utf-8'))
    except Exception as exc:
        raise ValueError(f"Fallo de desencriptación o autenticación JWE: {exc}") from exc


__all__ = [
    'get_jwe_key',
    'encrypt_payload_jwe',
    'decrypt_payload_jwe',
]
