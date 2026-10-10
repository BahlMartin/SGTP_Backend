"""
Serializadores DRF y Esquemas para Tickets Asistenciales y Estudios Asociados.
"""
from typing import Any, Dict
from rest_framework import serializers

from app.models.ticket import (
    Ticket,
    TicketEstudios,
    ClasificacionTriage,
)
from app.schemas.studies import EstudiosSerializer
from app.schemas.patient import PacienteSerializer
from app.models.patient import Paciente


class TicketEstudiosSerializer(serializers.ModelSerializer):
    estudio_detalle = EstudiosSerializer(source='estudio', read_only=True)

    class Meta:
        model = TicketEstudios
        fields = [
            'id',
            'estudio',
            'estudio_detalle',
            'estado',
            'observaciones',
        ]


class TicketCreateSerializer(serializers.ModelSerializer):
    """
    Serializador de entrada para la emisión de Tickets en Admisión.
    Soporta vincular un paciente existente por ID o crearlo/resolverlo automáticamente
    a partir de 'paciente_datos' ({ dni, nombre, apellidos, obra_social }).
    """
    num_totem = serializers.CharField(max_length=50, required=False, default='')
    paciente = serializers.PrimaryKeyRelatedField(
        queryset=Paciente.objects.all(),
        required=False,
        allow_null=True
    )
    paciente_datos = serializers.DictField(
        required=False,
        write_only=True,
        help_text="Datos del paciente para resolución o alta automática ({ dni, nombre, apellidos, obra_social })"
    )
    estudios_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        write_only=True,
        help_text="Lista de IDs de estudios del catálogo a vincular con el ticket"
    )

    class Meta:
        model = Ticket
        fields = [
            'id_ticket',
            'num_totem',
            'paciente',
            'paciente_datos',
            'clasificacion_triage',
            'justificacion_otro',
            'estudios_ids',
        ]
        read_only_fields = ['id_ticket']

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        from django.utils import timezone

        # Autogenerar número de tótem si no fue provisto
        if not attrs.get('num_totem') or not str(attrs.get('num_totem')).strip():
            count_hoy = Ticket.objects.filter(
                fecha_hora_admision__date=timezone.now().date()
            ).count() + 1
            attrs['num_totem'] = f"T-{count_hoy:03d}"

        # Resolver o crear paciente si se envió paciente_datos
        paciente = attrs.get('paciente')
        paciente_datos = attrs.get('paciente_datos')

        if not paciente and paciente_datos:
            dni_raw = paciente_datos.get('dni')
            if not dni_raw:
                raise serializers.ValidationError({
                    'paciente_datos': "El campo 'dni' es requerido dentro de paciente_datos."
                })
            try:
                dni_val = int(str(dni_raw).replace('.', '').strip())
            except (ValueError, TypeError):
                raise serializers.ValidationError({
                    'paciente_datos': "El DNI proporcionado debe ser numérico."
                })

            paciente_instancia, _ = Paciente.objects.get_or_create(
                dni=dni_val,
                defaults={
                    'nombre': str(paciente_datos.get('nombre', 'Sin Nombre')).strip(),
                    'apellidos': str(paciente_datos.get('apellidos', 'Sin Apellido')).strip(),
                    'obra_social': str(paciente_datos.get('obra_social', 'Particular')).strip(),
                    'num_obra_social': str(paciente_datos.get('num_obra_social', '')).strip()
                }
            )
            attrs['paciente'] = paciente_instancia
            attrs.pop('paciente_datos', None)
        elif not paciente:
            raise serializers.ValidationError({
                'paciente': "Debe especificar el ID de un paciente existente o proporcionar el objeto 'paciente_datos'."
            })

        triage = attrs.get('clasificacion_triage')
        justificacion = attrs.get('justificacion_otro')

        if triage == ClasificacionTriage.OTRO:
            if not justificacion or not justificacion.strip():
                raise serializers.ValidationError({
                    'justificacion_otro': "La justificación médica es obligatoria cuando la clasificación de triage es 'Otro'."
                })
        return attrs


class TicketDetailSerializer(serializers.ModelSerializer):
    """
    Serializador completo de salida para despliegue en pantallas y monitores de box.
    """
    paciente_detalle = PacienteSerializer(source='paciente', read_only=True)
    estudios = TicketEstudiosSerializer(many=True, read_only=True)
    box_numero = serializers.ReadOnlyField(source='box_actual.numero')
    personal_admision_nombre = serializers.SerializerMethodField()
    personal_admision_matricula = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            'id_ticket',
            'num_totem',
            'fecha_hora_admision',
            'personal_admision',
            'personal_admision_nombre',
            'personal_admision_matricula',
            'paciente',
            'paciente_detalle',
            'clasificacion_triage',
            'justificacion_otro',
            'estado',
            'box_actual',
            'box_numero',
            'estudios',
        ]
        read_only_fields = fields

    def get_personal_admision_nombre(self, obj: Ticket) -> str:
        if obj.personal_admision:
            return f"{obj.personal_admision.apellidos}, {obj.personal_admision.nombre}"
        return ""

    def get_personal_admision_matricula(self, obj: Ticket) -> str:
        if obj.personal_admision and obj.personal_admision.matricula:
            return str(obj.personal_admision.matricula)
        return ""


# Alias
TicketSerializer = TicketDetailSerializer

__all__ = [
    'TicketEstudiosSerializer',
    'TicketCreateSerializer',
    'TicketDetailSerializer',
    'TicketSerializer',
]
