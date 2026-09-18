"""
Modelos para registro y trazabilidad de Reportes Diarios Consolidados.
"""
from django.db import models
from django.utils import timezone
from auditlog.registry import auditlog


class HistorialReporteDiario(models.Model):
    """
    Registra cada ejecución del reporte diario generado por Celery a las 23:59 UTC.
    """
    id = models.AutoField(primary_key=True)
    fecha_reporte = models.DateField(default=timezone.now, db_index=True)
    total_pacientes_atendidos = models.IntegerField(default=0)
    total_estudios_realizados = models.IntegerField(default=0)
    destinatarios_notificados = models.TextField(help_text="Lista de emails a los que se remitió el reporte")
    fecha_hora_envio = models.DateTimeField(auto_now_add=True)
    exitoso = models.BooleanField(default=True)
    error_detalle = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'sgtp_historial_reportes'
        verbose_name = 'Historial de Reporte Diario'
        verbose_name_plural = 'Historial de Reportes Diarios'
        ordering = ['-fecha_hora_envio']

    def __str__(self) -> str:
        return f"Reporte {self.fecha_reporte} ({self.total_pacientes_atendidos} pacientes) - Éxito: {self.exitoso}"


auditlog.register(HistorialReporteDiario)

__all__ = ['HistorialReporteDiario']
