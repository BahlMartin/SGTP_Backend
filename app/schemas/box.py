"""
Serializadores DRF y Esquemas para Boxes y Asignaciones de Box.
"""
from rest_framework import serializers

from app.models.box import (
    Box,
    AsignacionesBox,
    MotivoCierreBox,
)


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


class AsignacionesBoxSerializer(serializers.ModelSerializer):
    box_numero = serializers.ReadOnlyField(source='box.numero')
    personal_email = serializers.ReadOnlyField(source='personal.email')
    ticket_totem = serializers.ReadOnlyField(source='ticket.num_totem')

    class Meta:
        model = AsignacionesBox
        fields = [
            'id',
            'box',
            'box_numero',
            'personal',
            'personal_email',
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


__all__ = [
    'BoxSerializer',
    'AsignacionesBoxSerializer',
    'CerrarAtencionSerializer',
]
