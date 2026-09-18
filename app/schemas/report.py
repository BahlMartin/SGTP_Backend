"""
Serializadores DRF y Esquemas para Reportes Diarios y Trazabilidad de Envíos.
"""
from rest_framework import serializers
from app.models.report import HistorialReporteDiario


class HistorialReporteDiarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistorialReporteDiario
        fields = [
            'id',
            'fecha_reporte',
            'total_pacientes_atendidos',
            'total_estudios_realizados',
            'destinatarios_notificados',
            'fecha_hora_envio',
            'exitoso',
            'error_detalle',
        ]


# Alias
ReportSchema = HistorialReporteDiarioSerializer

__all__ = [
    'HistorialReporteDiarioSerializer',
    'ReportSchema',
]
