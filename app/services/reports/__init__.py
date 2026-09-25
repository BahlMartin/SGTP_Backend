"""
Módulo de Reportes Asistenciales del SGTP.
Estructura modular desacoplada basada en el Patrón Fachada (Facade) y Principio de Responsabilidad Única (SRP).
"""
from app.services.reports.metrics import ReportMetricsService
from app.services.reports.pdf import ReportPdfGenerator
from app.services.reports.email import ReportEmailService
from app.services.reports.report_facade import ReportFacade, ReportService, ReportsService

__all__ = [
    'ReportMetricsService',
    'ReportPdfGenerator',
    'ReportEmailService',
    'ReportFacade',
    'ReportService',
    'ReportsService',
]
