"""
Tareas Asíncronas Celery para el módulo de Reportes.
Programada para ejecutarse a las 23:59 UTC mediante Celery Beat.
"""
import logging
from celery import shared_task
from app.services.reports_service import ReportService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def tarea_consolidar_y_enviar_reporte_diario(self) -> str:
    """
    Tarea Celery Beat que consolida el flujo diario asistencial, compila el PDF
    y lo despacha por correo SMTP a las autoridades del laboratorio (Jefa y Secretaría).
    """
    logger.info("Iniciando tarea programada Celery: Consolidación y despacho de reporte diario.")
    try:
        historial = ReportService.enviar_reporte_diario_por_email()
        resultado = (
            f"Reporte diario procesado con éxito (ID: {historial.id}). "
            f"Atendidos: {historial.total_pacientes_atendidos}. "
            f"Notificados: {historial.destinatarios_notificados}."
        )
        logger.info(resultado)
        return resultado
    except Exception as exc:
        logger.error("Fallo al ejecutar tarea de reporte diario: %s. Reintentando...", exc)
        raise self.retry(exc=exc)
