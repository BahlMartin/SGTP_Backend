"""
Serializadores DRF para Gestión de Turnos, Horas Extras y Planificación Mensual.
Desacoplado de user.py para garantizar mantenibilidad y responsabilidad única.
"""
from rest_framework import serializers
from app.models.shifts import PlanificacionHorasExtras, HabilitacionHoraria


class HabilitacionHorariaSerializer(serializers.ModelSerializer):
    aprobado_por_email = serializers.ReadOnlyField(source='aprobado_por.email')
    personal_email = serializers.ReadOnlyField(source='personal.email')

    class Meta:
        model = HabilitacionHoraria
        fields = [
            'id',
            'personal',
            'personal_email',
            'planificacion',
            'aprobado_por',
            'aprobado_por_email',
            'fecha',
            'hora_inicio',
            'hora_fin',
            'motivo',
            'activa',
        ]
        read_only_fields = ['id', 'aprobado_por', 'aprobado_por_email', 'personal_email']

    def validate(self, attrs):
        instance = HabilitacionHoraria(**attrs)
        request = self.context.get('request')
        if request and hasattr(request, 'user') and not instance.aprobado_por_id:
            instance.aprobado_por = request.user
        instance.clean()
        return attrs


class PlanificacionHorasExtrasSerializer(serializers.ModelSerializer):
    """
    Serializador para la planificación mensual de horas extras.
    Crea la cabecera mensual y en bloque (bulk) las habilitaciones diarias individuales.
    """
    fechas_seleccionadas = serializers.ListField(
        child=serializers.DateField(),
        write_only=True,
        required=True
    )
    aprobado_por_email = serializers.ReadOnlyField(source='aprobado_por.email')
    personal_email = serializers.ReadOnlyField(source='personal.email')
    habilitaciones_diarias_detalle = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PlanificacionHorasExtras
        fields = [
            'id',
            'personal',
            'personal_email',
            'aprobado_por',
            'aprobado_por_email',
            'anio',
            'mes',
            'tipo_extension',
            'hora_inicio',
            'hora_fin',
            'total_horas_mensual',
            'motivo',
            'activa',
            'fechas_seleccionadas',
            'habilitaciones_diarias_detalle',
            'fecha_creacion'
        ]
        read_only_fields = ['id', 'aprobado_por', 'aprobado_por_email', 'total_horas_mensual', 'fecha_creacion']

    def get_habilitaciones_diarias_detalle(self, obj):
        return [
            {
                'id': h.id,
                'fecha': str(h.fecha),
                'hora_inicio': str(h.hora_inicio)[:5],
                'hora_fin': str(h.hora_fin)[:5],
                'activa': h.activa
            }
            for h in obj.habilitaciones_diarias.filter(activa=True).order_by('fecha')
        ]

    def create(self, validated_data):
        fechas = validated_data.pop('fechas_seleccionadas', [])
        hora_inicio = validated_data['hora_inicio']
        hora_fin = validated_data['hora_fin']
        personal = validated_data['personal']
        request = self.context.get('request')
        aprobado_por = request.user if request and hasattr(request, 'user') else validated_data.get('aprobado_por')

        # Calcular horas diarias
        h_ini = hora_inicio.hour + hora_inicio.minute / 60.0
        h_fin = hora_fin.hour + hora_fin.minute / 60.0
        duracion_diaria = max(0.0, h_fin - h_ini)
        total_horas = round(len(fechas) * duracion_diaria, 2)

        validated_data['total_horas_mensual'] = total_horas
        validated_data['aprobado_por'] = aprobado_por

        # Si ya existía una planificación para este personal en ese mes y año, eliminarla/reemplazarla limpiamente
        PlanificacionHorasExtras.objects.filter(
            personal=personal,
            anio=validated_data['anio'],
            mes=validated_data['mes']
        ).delete()

        planificacion = PlanificacionHorasExtras.objects.create(**validated_data)

        # Generar detalle diario en HabilitacionHoraria
        habilitaciones_a_crear = [
            HabilitacionHoraria(
                personal=personal,
                planificacion=planificacion,
                aprobado_por=aprobado_por,
                fecha=fecha,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                motivo=validated_data['motivo'],
                activa=True
            )
            for fecha in fechas
        ]
        HabilitacionHoraria.objects.bulk_create(habilitaciones_a_crear)
        return planificacion


__all__ = [
    'HabilitacionHorariaSerializer',
    'PlanificacionHorasExtrasSerializer',
]
