"""
Serializadores DRF y Esquemas para Autenticación, Gestión de Personal y Turnos.
"""
from typing import Any, Dict
from rest_framework import serializers
from app.models.user import Personal, RolPersonal, HabilitacionHoraria, validar_solo_letras_min2


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class EmergencyUnlockSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    token_emergencia = serializers.CharField(required=True, write_only=True)


class DesbloqueoManualSerializer(serializers.Serializer):
    id_personal = serializers.IntegerField(required=True)


class PersonalAuthSerializer(serializers.ModelSerializer):
    """
    Serializador específico para respuestas de autenticación (Login).
    Devuelve únicamente la información de sesión requerida para el frontend.
    """
    apellido = serializers.CharField(source='apellidos', read_only=True)

    class Meta:
        model = Personal
        fields = [
            'id_personal',
            'matricula',
            'nombre',
            'apellidos',
            'apellido',
            'rol',
            'inicio_turno',
            'fin_turno',
        ]
        read_only_fields = fields


class PersonalSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Personal
        fields = [
            'id_personal',
            'email',
            'password',
            'nombre',
            'apellidos',
            'dni',
            'matricula',
            'rol',
            'activo',
            'cant_intentos',
            'inicio_turno',
            'fin_turno',
            'fecha_creacion',
        ]
        read_only_fields = ['id_personal', 'cant_intentos', 'fecha_creacion']

    def validate_nombre(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_apellidos(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        inicio = attrs.get('inicio_turno')
        fin = attrs.get('fin_turno')
        if (inicio and not fin) or (fin and not inicio):
            raise serializers.ValidationError(
                "Debe especificar tanto inicio_turno como fin_turno para definir la franja horaria."
            )
        return attrs


class HabilitacionHorariaSerializer(serializers.ModelSerializer):
    aprobado_por_nombre = serializers.ReadOnlyField(source='aprobado_por.email')
    personal_email = serializers.ReadOnlyField(source='personal.email')

    class Meta:
        model = HabilitacionHoraria
        fields = [
            'id',
            'personal',
            'personal_email',
            'aprobado_por',
            'aprobado_por_nombre',
            'fecha',
            'hora_inicio',
            'hora_fin',
            'motivo',
            'activa',
        ]
        read_only_fields = ['id', 'aprobado_por', 'aprobado_por_nombre', 'personal_email']


# Alias arquitectónicos
UserSchema = PersonalSerializer
LoginRequestSchema = LoginSerializer
EmergencyUnlockSchema = EmergencyUnlockSerializer

__all__ = [
    'LoginSerializer',
    'EmergencyUnlockSerializer',
    'DesbloqueoManualSerializer',
    'PersonalAuthSerializer',
    'PersonalSerializer',
    'HabilitacionHorariaSerializer',
    'UserSchema',
    'LoginRequestSchema',
    'EmergencyUnlockSchema',
]
