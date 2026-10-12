"""
Serializadores DRF y Esquemas para Autenticación, Gestión de Personal y Turnos.
"""
from typing import Any, Dict
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from app.models.user import Personal, HabilitacionHoraria, DiaLaboralPersonal
from app.core.validators import validar_solo_letras_min2


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class EmergencyUnlockSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    token_emergencia = serializers.CharField(required=True, write_only=True)


class DesbloqueoManualSerializer(serializers.Serializer):
    id_personal = serializers.IntegerField(required=True)


class DiaLaboralPersonalSerializer(serializers.ModelSerializer):
    dia_nombre = serializers.CharField(source='get_dia_semana_display', read_only=True)

    class Meta:
        model = DiaLaboralPersonal
        fields = ['dia_semana', 'dia_nombre']


class PersonalAuthSerializer(serializers.ModelSerializer):
    """
    Serializador específico para respuestas de autenticación (Login).
    Devuelve únicamente la información de sesión requerida para el frontend.
    """
    dias_laborales_detalle = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Personal
        fields = [
            'id_personal',
            'email',
            'matricula',
            'nombre',
            'apellidos',
            'rol',
            'inicio_turno',
            'fin_turno',
            'dias_laborales_detalle'
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_dias_laborales_detalle(self, obj):
        return list(obj.dias_laborales.values_list('dia_semana', flat=True))


class PersonalSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    dias_laborales = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        required=False,
        write_only=True
    )
    dias_laborales_detalle = serializers.SerializerMethodField(read_only=True)
    habilitaciones_activas_hoy = serializers.SerializerMethodField(read_only=True)

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
            'dias_laborales',
            'dias_laborales_detalle',
            'habilitaciones_activas_hoy'
        ]
        read_only_fields = ['id_personal', 'cant_intentos']

    @extend_schema_field(serializers.ListField(child=serializers.IntegerField()))
    def get_dias_laborales_detalle(self, obj):
        return list(obj.dias_laborales.values_list('dia_semana', flat=True))

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_habilitaciones_activas_hoy(self, obj):
        hoy = timezone.localdate()
        habilitaciones = obj.habilitaciones_horarias.filter(fecha=hoy, activa=True).order_by('hora_inicio')
        return [
            {
                'id': h.id,
                'hora_inicio': str(h.hora_inicio)[:5],
                'hora_fin': str(h.hora_fin)[:5],
                'motivo': h.motivo,
                'aprobado_por_email': h.aprobado_por.email if h.aprobado_por else None
            }
            for h in habilitaciones
        ]

    def validate_nombre(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate_apellidos(self, value: str) -> str:
        validar_solo_letras_min2(value)
        return value.strip()

    def validate(self, attributes: Dict[str, Any]) -> Dict[str, Any]:
        inicio = attributes.get('inicio_turno')
        fin = attributes.get('fin_turno')
        if (inicio and not fin) or (fin and not inicio):
            raise serializers.ValidationError(
                "Debe especificar tanto inicio_turno como fin_turno para definir la franja horaria."
            )
        return attributes

    def create(self, validated_data):
        dias = validated_data.pop('dias_laborales', [0, 1, 2, 3, 4])
        user = super().create(validated_data)
        for d in dias:
            DiaLaboralPersonal.objects.create(personal=user, dia_semana=d)
        return user

    def update(self, instance, validated_data):
        dias = validated_data.pop('dias_laborales', None)
        instance = super().update(instance, validated_data)
        if dias is not None:
            instance.dias_laborales.all().delete()
            for d in dias:
                DiaLaboralPersonal.objects.create(personal=instance, dia_semana=d)
        return instance


# Re-exportación desde app.schemas.shifts para mantener arquitectura limpia
from app.schemas.shifts import HabilitacionHorariaSerializer, PlanificacionHorasExtrasSerializer

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
    'DiaLaboralPersonalSerializer',
    'HabilitacionHorariaSerializer',
    'PlanificacionHorasExtrasSerializer',
    'UserSchema',
    'LoginRequestSchema',
    'EmergencyUnlockSchema',
]
