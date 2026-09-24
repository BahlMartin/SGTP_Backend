"""
Serializadores DRF y Esquemas para Boxes, Tickets, Asignaciones y Estudios Asociados.
"""
from typing import Any, Dict, List
from rest_framework import serializers
from app.models.triage import (
    Box,
    Ticket,
    TicketEstudios,
    AsignacionesBox,
    ClasificacionTriage,
    MotivoCierreBox,
)
from app.schemas.studies import EstudiosSerializer
from app.schemas.patient import PacienteSerializer


class BoxSerializer(serializers.ModelSerializer):
    class Meta:
        model = Box
        fields = [
            'id',
            'numero',
            'estado',
            'activo',
            'discapacidad',
        ]


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
    """
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
            'clasificacion_triage',
            'justificacion_otro',
            'estudios_ids',
        ]
        read_only_fields = ['id_ticket']

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
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

    class Meta:
        model = Ticket
        fields = [
            'id_ticket',
            'num_totem',
            'fecha_hora_admision',
            'personal_admision',
            'personal_admision_nombre',
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


class AsignacionesBoxSerializer(serializers.ModelSerializer):
    box_numero = serializers.ReadOnlyField(source='box.numero')
    personal_nombre = serializers.ReadOnlyField(source='personal.email')
    ticket_totem = serializers.ReadOnlyField(source='ticket.num_totem')

    class Meta:
        model = AsignacionesBox
        fields = [
            'id',
            'box',
            'box_numero',
            'personal',
            'personal_nombre',
            'ticket',
            'ticket_totem',
            'motivo_cierre',
            'fecha_hora_inicio',
            'fecha_hora_final',
        ]


class CerrarAtencionSerializer(serializers.Serializer):
    motivo_cierre = serializers.ChoiceField(
        choices=MotivoCierreBox.choices,
        default=MotivoCierreBox.FINALIZADO
    )


# Alias
TicketSerializer = TicketDetailSerializer

__all__ = [
    'BoxSerializer',
    'TicketEstudiosSerializer',
    'TicketCreateSerializer',
    'TicketDetailSerializer',
    'TicketSerializer',
    'AsignacionesBoxSerializer',
    'CerrarAtencionSerializer',
]
