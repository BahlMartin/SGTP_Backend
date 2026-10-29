"""
Patrón Fachada (Facade) para la Gestión de Reportes Asistenciales del SGTP.
Orquesta los subsistemas especializados:
- ReportMetricsService: Consolidación y analítica de base de datos
- ReportPdfGenerator: Compilación de documentos PDF en memoria
- ReportExcelGenerator: Compilación de libros Excel (.xlsx) multi-hoja en memoria
- ReportEmailService: Despacho SMTP y trazabilidad de auditoría
"""
from typing import Dict, Any, Optional, List
from datetime import date

from app.models.report import HistorialReporteDiario
from app.services.reports.metrics import ReportMetricsService
from app.services.reports.pdf import ReportPdfGenerator
from app.services.reports.excel import ReportExcelGenerator
from app.services.reports.email import ReportEmailService


class ReportFacade:
    """
    Fachada unificada que expone una interfaz simple y cohesiva para el flujo de reportes,
    delegando cada tarea a su subsistema especializado correspondiente.
    """

    @classmethod
    def consolidar_metricas_diarias(
        cls,
        fecha_consulta: Optional[date] = None,
        incluir_detalle_excel: bool = False,
        incluir_rendimiento_personal: bool = False
    ) -> Dict[str, Any]:
        """
        Delega el cálculo de indicadores asistenciales a ReportMetricsService.
        Si incluir_detalle_excel=True, incluye además los desgloses y listados nominales
        para las 6 hojas del reporte Excel (.xlsx).
        """
        return ReportMetricsService.consolidar(
            fecha_consulta,
            incluir_detalle_excel=incluir_detalle_excel,
            incluir_rendimiento_personal=incluir_rendimiento_personal
        )

    @classmethod
    def generar_pdf_reporte(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Delega la compilación y renderizado de PDF a ReportPdfGenerator.
        """
        return ReportPdfGenerator.generar(metricas)

    @classmethod
    def generar_excel_reporte(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Delega la compilación del libro Excel (.xlsx) de 6 hojas a ReportExcelGenerator.
        """
        return ReportExcelGenerator.generar(metricas)

    @classmethod
    def enviar_reporte_diario_por_email(
        cls,
        fecha_consulta: Optional[date] = None,
        destinatarios: Optional[List[str]] = None
    ) -> Optional[HistorialReporteDiario]:
        """
        Orquesta el flujo completo:
        1. Valida destinatarios (si no hay, no envía y retorna None).
        2. Consolida métricas asistenciales (incluyendo detalle para Excel y rendimiento de personal).
        3. Compila el documento PDF oficial y el libro Excel (.xlsx) multi-hoja.
        4. Despacha por correo SMTP al destinatario con ambos adjuntos y registra auditoría.
        """
        if not destinatarios:
            return None

        metricas = cls.consolidar_metricas_diarias(
            fecha_consulta,
            incluir_detalle_excel=True,
            incluir_rendimiento_personal=True
        )
        pdf_bytes = cls.generar_pdf_reporte(metricas)
        excel_bytes = cls.generar_excel_reporte(metricas)
        return ReportEmailService.despachar(
            metricas,
            pdf_bytes,
            destinatarios=destinatarios,
            excel_bytes=excel_bytes
        )


# Alias para compatibilidad de nomenclatura
ReportService = ReportFacade
ReportsService = ReportFacade

__all__ = ['ReportFacade', 'ReportService', 'ReportsService']
