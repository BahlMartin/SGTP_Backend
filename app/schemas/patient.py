"""
Serializadores DRF y Esquemas para Pacientes y Soporte de Cifrado FLE.
"""
from rest_framework import serializers
from app.models.patient import Paciente
from app.models.user import validar_solo_letras_min2


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
            'num_obra_social',
            'nombre',
            'apellidos',
            'fecha_creacion',
        ]
        read_only_fields = ['id_paciente', 'fecha_creacion']

    def validate_nombre(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_apellidos(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_dni(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("El DNI debe ser un número entero positivo.")
        return value


# Alias estándar
PatientSchema = PacienteSerializer

__all__ = [
    'PacienteSerializer',
    'PatientSchema',
]
