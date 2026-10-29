"""
Serializadores DRF para Auditoría Operacional y Geolocalización (SGTP).
"""
from rest_framework import serializers
from app.models.audit import EventoAuditoria
from app.models.user import Personal


class PersonalAuditSummarySerializer(serializers.ModelSerializer):
    """Resumen de datos de empleado para filas de auditoría y drawer lateral."""
    id = serializers.IntegerField(source='id_personal', read_only=True)
    turno = serializers.SerializerMethodField()

    class Meta:
        model = Personal
        fields = ['id', 'id_personal', 'nombre', 'apellidos', 'email', 'rol', 'turno']

    def get_turno(self, obj) -> str:
        if obj and obj.inicio_turno and obj.fin_turno:
            return f"{obj.inicio_turno.strftime('%H:%M')}–{obj.fin_turno.strftime('%H:%M')}"
        return "Sin turno asignado"


class EventoAuditoriaListSerializer(serializers.ModelSerializer):
    """Serializador para filas de tabla de auditoría con datos ligeros de usuario."""
    usuario = PersonalAuditSummarySerializer(read_only=True)
    hora = serializers.SerializerMethodField()

    class Meta:
        model = EventoAuditoria
        fields = [
            'id',
            'fecha',
            'hora',
            'usuario',
            'rol_usuario',
            'email_intentado',
            'categoria',
            'accion',
            'resultado',
            'descripcion',
            'entidad_tipo',
            'entidad_id',
            'metadata',
            'cambios',
            'alertas',
            'ip',
            'ip_confiable',
            'dispositivo',
            'geo_ip_ciudad',
            'geo_ip_region',
            'geo_ip_pais',
            'geo_ip_estado',
            'geo_nav_lat',
            'geo_nav_lon',
            'geo_nav_precision_m',
            'geo_nav_distancia_km',
            'geo_nav_coincide_ip',
            'geo_nav_estado',
            'acceso_externo',
        ]

    def get_hora(self, obj) -> str:
        if obj.fecha:
            return obj.fecha.strftime('%H:%M')
        return ''


class EventoAuditoriaDetailSerializer(EventoAuditoriaListSerializer):
    """Serializador detallado para el Drawer lateral con payload técnico y traza forense."""
    class Meta(EventoAuditoriaListSerializer.Meta):
        fields = EventoAuditoriaListSerializer.Meta.fields + ['ip_cadena', 'user_agent']


class ReportarUbicacionSerializer(serializers.Serializer):
    """Payload enviado por el navegador para reportar coordenadas GPS o denegación post-login."""
    lat = serializers.FloatField(required=False, allow_null=True)
    lon = serializers.FloatField(required=False, allow_null=True)
    precision_m = serializers.FloatField(required=False, allow_null=True)
    denegada = serializers.BooleanField(required=False, default=False)

