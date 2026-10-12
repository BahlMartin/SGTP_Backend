"""
Serializadores DRF y Esquemas para Boxes y Asignaciones de Box.
"""
from rest_framework import serializers

from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
    MotivoCierreBox,
)
from app.models.user import Personal


class PersonalBoxSummarySerializer(serializers.ModelSerializer):
    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = Personal
        fields = [
            'id_personal',
            'nombre',
            'apellidos',
            'nombre_completo',
            'matricula',
            'email',
            'rol',
        ]

    def get_nombre_completo(self, obj: Personal) -> str:
        if obj.apellidos and obj.nombre:
            return f"{obj.apellidos}, {obj.nombre}"
        return obj.nombre or obj.email


class BoxSerializer(serializers.ModelSerializer):
    personal_actual_detalle = serializers.SerializerMethodField()
    paciente_actual_detalle = serializers.SerializerMethodField()

    class Meta:
        model = Box
        fields = [
            'id',
            'numero',
            'estado',
            'activo',
            'discapacidad',
            'personal_actual',
            'personal_actual_detalle',
            'paciente_actual_detalle',
        ]

    def get_personal_actual_detalle(self, obj: Box):
        # 1. Asignación directa persistida en el Box
        if obj.personal_actual:
            return PersonalBoxSummarySerializer(obj.personal_actual).data

        # 2. Respaldo por asignación activa en atención
        asig_abierta = obj.asignaciones.filter(fecha_hora_final__isnull=True).select_related('personal').first()
        if asig_abierta and asig_abierta.personal:
            otro_box_asignado = Box.objects.filter(personal_actual=asig_abierta.personal).exclude(pk=obj.pk).exists()
            if not otro_box_asignado:
                return PersonalBoxSummarySerializer(asig_abierta.personal).data

        return None

    def get_paciente_actual_detalle(self, obj: Box):
        if obj.estado != EstadoBox.EN_ATENCION:
            return None

        asig_abierta = obj.asignaciones.filter(fecha_hora_final__isnull=True).select_related('ticket__paciente').first()
        if asig_abierta and asig_abierta.ticket:
            ticket = asig_abierta.ticket
            paciente = ticket.paciente
            return {
                'id_ticket': str(ticket.id_ticket),
                'num_totem': ticket.num_totem,
                'clasificacion_triage': ticket.clasificacion_triage,
                'paciente_nombre': f"{paciente.apellidos}, {paciente.nombre}" if paciente else "Paciente s/d"
            }
        return None


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
