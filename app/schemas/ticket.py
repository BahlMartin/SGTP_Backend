"""
Serializadores DRF y Esquemas para Tickets Asistenciales y Estudios Asociados.
"""
from typing import Any, Dict
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app.models.ticket import (
    Ticket,
    TicketEstudios,
    ClasificacionTriage,
)
from app.schemas.studies import EstudiosSerializer
from app.schemas.patient import PacienteSerializer
from app.models.patient import Paciente
from app.services.patient_service import PatientService


class TicketEstudiosSerializer(serializers.ModelSerializer):
    estudio_detalle = EstudiosSerializer(source='estudio', read_only=True)
    modificado_por_nombre = serializers.SerializerMethodField()
    asignacion_box_id = serializers.ReadOnlyField(source='asignacion_box.id')

    class Meta:
        model = TicketEstudios
        fields = [
            'id',
            'estudio',
            'estudio_detalle',
            'estado',
            'origen',
            'asignacion_box_id',
            'motivo_modificacion',
            'modificado_por_nombre',
            'fecha_hora_modificacion',
            'observaciones',
        ]

    def get_modificado_por_nombre(self, obj: TicketEstudios) -> str:
        if obj.modificado_por:
            return f"{obj.modificado_por.apellidos}, {obj.modificado_por.nombre}"
        return ""


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

        # Normalizar o autogenerar número de tótem
        raw_num_totem = str(attrs.get('num_totem') or '').strip()
        if raw_num_totem:
            import re
            match = re.match(r'^(Ext|G|Med|Csl)[-\s]?(\d+)$', raw_num_totem, re.IGNORECASE)
            if match:
                prefijo_raw, num_str = match.groups()
                mapa_prefijos = {'ext': 'Ext', 'g': 'G', 'med': 'Med', 'csl': 'Csl'}
                prefijo = mapa_prefijos.get(prefijo_raw.lower(), prefijo_raw.capitalize())
                attrs['num_totem'] = f"{prefijo}-{int(num_str):02d}"
            else:
                attrs['num_totem'] = raw_num_totem
        else:
            count_hoy = Ticket.objects.filter(
                fecha_hora_admision__date=timezone.now().date()
            ).count() + 1
            attrs['num_totem'] = f"T-{count_hoy:03d}"

        # Resolver o crear paciente si se envió paciente_datos
        paciente = attrs.get('paciente')
        paciente_datos = attrs.get('paciente_datos')

        if not paciente and paciente_datos:
            paciente_instancia = PatientService.resolver_o_crear_paciente_para_ticket(paciente_datos)
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
    fecha_estimada_entrega = serializers.SerializerMethodField()
    demora_horas_max = serializers.SerializerMethodField()
    estudio_mayor_demora = serializers.SerializerMethodField()

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
            'fecha_estimada_entrega',
            'demora_horas_max',
            'estudio_mayor_demora',
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

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_fecha_estimada_entrega(self, obj: Ticket):
        fecha = getattr(obj, 'fecha_estimada_entrega', None)
        if not fecha:
            from app.services.triage_service import TriageService
            from django.utils import timezone
            base = getattr(obj, 'fecha_hora_admision', None) or timezone.now()
            fecha, _, _ = TriageService.calcular_fecha_estimada_entrega(obj, fecha_base=base)
        return fecha.isoformat() if hasattr(fecha, 'isoformat') else (str(fecha) if fecha else None)

    @extend_schema_field(serializers.IntegerField())
    def get_demora_horas_max(self, obj: Ticket) -> int:
        from app.services.triage_service import TriageService
        _, max_horas, _ = TriageService.calcular_fecha_estimada_entrega(obj)
        return max_horas

    @extend_schema_field(serializers.CharField())
    def get_estudio_mayor_demora(self, obj: Ticket) -> str:
        from app.services.triage_service import TriageService
        _, _, mayor = TriageService.calcular_fecha_estimada_entrega(obj)
        return mayor



class TicketHistorialDetailSerializer(TicketDetailSerializer):
    """
    Serializador enriquecido para consultas asistenciales de detalle de ticket, historial clínico y auditoría.
    Extrae la trazabilidad de atención en Box (Box y Profesional con matrícula) desde la tabla de asignaciones_box.
    """
    box_numero = serializers.SerializerMethodField()
    personal_box_nombre = serializers.SerializerMethodField()
    personal_box_matricula = serializers.SerializerMethodField()
    fecha_hora_atencion_box = serializers.SerializerMethodField()
    motivo_cierre_box = serializers.SerializerMethodField()
    observaciones_cierre_box = serializers.SerializerMethodField()

    class Meta(TicketDetailSerializer.Meta):
        fields = TicketDetailSerializer.Meta.fields + [
            'personal_box_nombre',
            'personal_box_matricula',
            'fecha_hora_atencion_box',
            'motivo_cierre_box',
            'observaciones_cierre_box',
        ]
        read_only_fields = fields

    def _get_ultima_asignacion(self, obj: Ticket):
        if hasattr(obj, '_prefetched_objects_cache') and 'asignaciones_historial' in obj._prefetched_objects_cache:
            asignaciones = list(obj.asignaciones_historial.all())
            return asignaciones[0] if asignaciones else None
        return obj.asignaciones_historial.select_related('personal', 'box').order_by('-fecha_hora_inicio').first()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_box_numero(self, obj: Ticket):
        asig = self._get_ultima_asignacion(obj)
        if asig and asig.box:
            return str(asig.box.numero)
        if obj.box_actual:
            return str(obj.box_actual.numero)
        return None

    def get_personal_box_nombre(self, obj: Ticket) -> str:
        asig = self._get_ultima_asignacion(obj)
        if asig and asig.personal:
            return f"{asig.personal.apellidos}, {asig.personal.nombre}"
        return ""

    def get_personal_box_matricula(self, obj: Ticket) -> str:
        asig = self._get_ultima_asignacion(obj)
        if asig and asig.personal and asig.personal.matricula:
            return str(asig.personal.matricula)
        return ""

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_fecha_hora_atencion_box(self, obj: Ticket):
        asig = self._get_ultima_asignacion(obj)
        return asig.fecha_hora_inicio if asig else None

    def get_motivo_cierre_box(self, obj: Ticket) -> str:
        asig = self._get_ultima_asignacion(obj)
        return asig.motivo_cierre if asig and asig.motivo_cierre else ""

    def get_observaciones_cierre_box(self, obj: Ticket) -> str:
        asig = self._get_ultima_asignacion(obj)
        return asig.observaciones_cierre if asig and getattr(asig, 'observaciones_cierre', None) else ""


# Alias
TicketSerializer = TicketDetailSerializer

__all__ = [
    'TicketEstudiosSerializer',
    'TicketCreateSerializer',
    'TicketDetailSerializer',
    'TicketHistorialDetailSerializer',
    'TicketSerializer',
]
