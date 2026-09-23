"""
Validadores reutilizables para modelos y esquemas del SGTP.
Centraliza las reglas de validación de campos y datos de negocio transversales.
"""
import re
from typing import Any, Optional
from django.core.exceptions import ValidationError


def validar_solo_letras_min2(valor: Any) -> None:
    """
    Valida que el valor tenga un mínimo de 2 caracteres y solo contenga letras
    (incluyendo tildes, diéresis y 'ñ') y espacios.
    """
    if valor is None:
        return
    texto = str(valor).strip()
    if len(texto) < 2:
        raise ValidationError("Debe contener un mínimo de 2 caracteres.")
    if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]+$', texto):
        raise ValidationError("Solo se admiten caracteres alfabéticos y espacios.")


def validar_dni_positivo(valor: Optional[int]) -> None:
    """
    Valida que el DNI sea un número entero positivo mayor a cero.
    """
    if valor is not None and valor <= 0:
        raise ValidationError({'dni': "El DNI debe ser un número entero positivo válido."})


__all__ = [
    'validar_solo_letras_min2',
    'validar_dni_positivo',
]
