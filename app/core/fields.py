"""
Módulo de campos personalizados para Field-Level Encryption (FLE).
Utiliza Fernet (AES-128-CBC + HMAC-SHA256) con clave centralizada desde .env.
"""
import base64
from typing import Any, Optional
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def get_fernet_cipher() -> Fernet:
    """
    Obtiene la instancia de Fernet utilizando la clave configurada en .env.
    No admite claves hardcodeadas o valores por defecto inseguros.
    """
    raw_key = getattr(settings, 'FERNET_ENCRYPTION_KEY', None)
    if not raw_key:
        raise ImproperlyConfigured(
            "FERNET_ENCRYPTION_KEY no está configurada en .env ni en settings."
        )

    # Si la clave ya es base64 de 44 caracteres apta para Fernet, usarla directamente
    key_bytes = raw_key.strip().encode('utf-8')
    try:
        return Fernet(key_bytes)
    except (ValueError, TypeError):
        # Si la clave tiene exactamente 32 bytes en texto plano, codificar a base64 urlsafe
        if len(key_bytes) == 32:
            encoded_key = base64.urlsafe_b64encode(key_bytes)
            return Fernet(encoded_key)
        raise ImproperlyConfigured(
            "FERNET_ENCRYPTION_KEY inválida en .env. Debe ser una clave Fernet válida "
            "(32 bytes codificados en Base64 URL-safe)."
        )


class FernetEncryptedCharField(models.CharField):
    """
    Campo CharField que encripta de forma transparente antes de escribir en la BD
    y desencripta automáticamente al leer.
    Garantiza que en la base de datos los datos sensibles residan cifrados.
    """

    description = "Campo CharField con Field-Level Encryption transparente mediante Fernet"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Los ciphertexts de Fernet son más largos que el texto plano; asegurar max_length suficiente
        kwargs.setdefault('max_length', 512)
        super().__init__(*args, **kwargs)

    def get_internal_type(self) -> str:
        return "CharField"

    def from_db_value(
        self, value: Optional[str], expression: Any, connection: Any
    ) -> Optional[str]:
        """Desencripta el valor al recuperarlo de la base de datos."""
        if value is None or value == "":
            return value
        return self._decrypt(value)

    def to_python(self, value: Optional[str]) -> Optional[str]:
        """Convierte y valida el valor hacia Python."""
        if value is None or value == "":
            return value
        # Si ya es texto plano legible o si es ciphertext, intenta desencriptar
        return self._decrypt(value)

    def get_prep_value(self, value: Optional[str]) -> Optional[str]:
        """Encripta el valor antes de persistir en base de datos."""
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return self._encrypt(str(value))

    def _encrypt(self, plaintext: str) -> str:
        """Cifra el texto plano a token Fernet seguro."""
        try:
            cipher = get_fernet_cipher()
            token = cipher.encrypt(plaintext.encode('utf-8'))
            return token.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Error al cifrar campo FLE: {e}") from e

    def _decrypt(self, ciphertext: str) -> str:
        """Desencripta token Fernet a texto plano. Si no es un token cifrado, lo retorna."""
        try:
            cipher = get_fernet_cipher()
            decrypted_bytes = cipher.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except (InvalidToken, Exception):
            # Si el valor ya está en plano (por ejemplo, recién seteado en la instancia)
            return ciphertext


__all__ = [
    'get_fernet_cipher',
    'FernetEncryptedCharField',
]
