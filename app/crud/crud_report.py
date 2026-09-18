"""
Operaciones CRUD para Historial de Reportes Diarios.
"""
from typing import Optional, List
from django.utils import timezone
from app.models.report import HistorialReporteDiario


class CRUDReport:
    """Capa de acceso a datos para Reportes Diarios."""

    @staticmethod
    def get_latest() -> Optional[HistorialReporteDiario]:
        return HistorialReporteDiario.objects.order_by('-fecha_hora_envio').first()

    @staticmethod
    def get_by_date(fecha) -> List[HistorialReporteDiario]:
        return list(HistorialReporteDiario.objects.filter(fecha_reporte=fecha))

    @staticmethod
    def create_log(
        total_pacientes: int,
        total_estudios: int,
        destinatarios: str,
        exitoso: bool = True,
        error_detalle: str = ''
    ) -> HistorialReporteDiario:
        return HistorialReporteDiario.objects.create(
            fecha_reporte=timezone.now().date(),
            total_pacientes_atendidos=total_pacientes,
            total_estudios_realizados=total_estudios,
            destinatarios_notificados=destinatarios,
            exitoso=exitoso,
            error_detalle=error_detalle
        )


crud_report = CRUDReport()
