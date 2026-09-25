"""
Validadores reutilizables para modelos y esquemas del SGTP.
Centraliza las reglas de validación de campos y datos de negocio transversales.
"""
from datetime import datetime, date
import re
from typing import Any, Optional
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError


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
        raise ValidationError("El DNI debe ser un número entero positivo válido.")


def validar_texto(valor: Any, mensaje: Optional[str] = None) -> None:
    """
    Valida que el valor no sea nulo ni consista únicamente en espacios en blanco.
    """
    if valor is None or not str(valor).strip():
        raise ValidationError(mensaje or "El texto no puede estar vacío.")


def validar_formato_fecha(valor: Optional[Any], formato: str = '%Y-%m-%d') -> Optional[date]:
    """
    Valida y parsea una fecha opcional.
    - Si el valor es None o vacío, retorna None.
    - Si ya es un objeto datetime.date (o datetime), retorna el objeto date.
    - Si es string, intenta parsearlo con el formato YYYY-MM-DD.
    - Si el formato es inválido, lanza rest_framework.exceptions.ValidationError
      con el código y estructura estándar {"error": "FECHA_INVALIDA", "detail": "..."}.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    if not texto:
        return None

    try:
        return datetime.strptime(texto, formato).date()
    except (ValueError, TypeError):
        raise DRFValidationError(
            {"error": "FECHA_INVALIDA", "detail": f"Formato de fecha inválido. Utilice {formato}."},
            code="FECHA_INVALIDA"
        )


__all__ = [
    'validar_solo_letras_min2',
    'validar_dni_positivo',
    'validar_texto',
    'validar_formato_fecha',
]
