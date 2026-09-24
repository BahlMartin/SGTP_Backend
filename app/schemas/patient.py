"""
Serializadores DRF y Esquemas para Pacientes y Soporte de Cifrado FLE.
"""
from rest_framework import serializers
from app.models.patient import Paciente
from app.core.validators import validar_solo_letras_min2, validar_dni_positivo, validar_texto


class PacienteSerializer(serializers.ModelSerializer):
    """
    Serializador para el modelo Paciente.
    Maneja la serialización transparente de campos cifrados con Fernet.
    """

    class Meta:
        model = Paciente
        fields = [
            'id_paciente',
            'dni',
            'obra_social',
            'num_obra_social',
            'nombre',
            'apellidos',
            'fecha_creacion',
        ]
        read_only_fields = ['id_paciente', 'fecha_creacion']

    def validate_obra_social(self, value: str) -> str:
        validar_texto(value, "El nombre de la obra social es obligatorio.")
        return value.strip()

    def validate_nombre(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_apellidos(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_dni(self, value: int) -> int:
        validar_dni_positivo(value)
        return value


# Alias estándar
PatientSchema = PacienteSerializer

__all__ = [
    'PacienteSerializer',
    'PatientSchema',
]
