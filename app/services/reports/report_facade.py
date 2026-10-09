"""
Patrón Fachada (Facade) para la Gestión de Reportes Asistenciales del SGTP.
Orquesta los subsistemas especializados:
- ReportMetricsService: Consolidación y analítica de base de datos
- ReportPdfGenerator: Compilación de documentos en memoria
- ReportEmailService: Despacho SMTP y trazabilidad de auditoría
"""
from typing import Dict, Any, Optional, List
from datetime import date

from app.models.report import HistorialReporteDiario
from app.services.reports.metrics import ReportMetricsService
from app.services.reports.pdf import ReportPdfGenerator
from app.services.reports.email import ReportEmailService


class ReportFacade:
    """
    Fachada unificada que expone una interfaz simple y cohesiva para el flujo de reportes,
    delegando cada tarea a su subsistema especializado correspondiente.
    """

    @classmethod
    def consolidar_metricas_diarias(cls, fecha_consulta: Optional[date] = None) -> Dict[str, Any]:
        """
        Delega el cálculo de indicadores asistenciales a ReportMetricsService.
        """
        return ReportMetricsService.consolidar(fecha_consulta)

    @classmethod
    def generar_pdf_reporte(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Delega la compilación y renderizado de PDF a ReportPdfGenerator.
        """
        return ReportPdfGenerator.generar(metricas)

    @classmethod
    def enviar_reporte_diario_por_email(
        cls,
        fecha_consulta: Optional[date] = None,
        destinatarios: Optional[List[str]] = None
    ) -> Optional[HistorialReporteDiario]:
        """
        Orquesta el flujo completo:
        1. Valida destinatarios (si no hay, no envía y retorna None).
        2. Consolida métricas asistenciales.
        3. Compila el documento PDF oficial.
        4. Despacha por correo SMTP al destinatario y registra auditoría.
        """
        if not destinatarios:
            return None

        metricas = cls.consolidar_metricas_diarias(fecha_consulta)
        pdf_bytes = cls.generar_pdf_reporte(metricas)
        return ReportEmailService.despachar(metricas, pdf_bytes, destinatarios=destinatarios)


# Alias para compatibilidad de nomenclatura
ReportService = ReportFacade
ReportsService = ReportFacade

__all__ = ['ReportFacade', 'ReportService', 'ReportsService']
