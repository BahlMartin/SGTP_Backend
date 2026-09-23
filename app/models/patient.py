"""
Modelo de Pacientes con Cifrado a Nivel de Campo (Field-Level Encryption - FLE).
Garantiza confidencialidad de datos médicos (PHI) en la base de datos.
"""
from django.db import models
from django.core.exceptions import ValidationError
from auditlog.registry import auditlog

from app.models.common import SoftDeleteModel
from app.core.fields import FernetEncryptedCharField
from app.core.validators import validar_solo_letras_min2, validar_dni_positivo


class Paciente(SoftDeleteModel):
    """
    Representa a un paciente ingresado en el sistema hospitalario.
    Los campos identificatorios sensibles son cifrados en reposo mediante Fernet.
    """
    id_paciente = models.AutoField(primary_key=True)
    dni = models.IntegerField(
        unique=True,
        db_index=True,
        verbose_name="Documento Nacional de Identidad"
    )
    num_obra_social = FernetEncryptedCharField(
        max_length=512,
        verbose_name="Número de Obra Social / Cobertura Médica (Cifrado FLE)"
    )
    nombre = FernetEncryptedCharField(
        max_length=512,
        validators=[validar_solo_letras_min2],
        verbose_name="Nombre(s) (Cifrado FLE)"
    )
    apellidos = FernetEncryptedCharField(
        max_length=512,
        validators=[validar_solo_letras_min2],
        verbose_name="Apellido(s) (Cifrado FLE)"
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de Alta en Sistema"
    )

    class Meta:
        db_table = 'sgtp_paciente'
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        ordering = ['dni']

    def clean(self) -> None:
        super().clean()
        validar_dni_positivo(self.dni)
        if self.nombre:
            validar_solo_letras_min2(str(self.nombre))
        if self.apellidos:
            validar_solo_letras_min2(str(self.apellidos))

    def __str__(self) -> str:
        return f"Paciente DNI: {self.dni} - {self.apellidos}, {self.nombre}"


# Registro de auditoría
auditlog.register(Paciente)

__all__ = ['Paciente']
