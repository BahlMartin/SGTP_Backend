"""
Tareas Asíncronas Celery para el módulo de Reportes.
Programada para ejecutarse a las 23:59 UTC mediante Celery Beat.
"""
import logging
from celery import shared_task
from app.services.reports.report_facade import ReportFacade

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def tarea_consolidar_y_enviar_reporte_diario(self) -> str:
    """
    Tarea Celery Beat que consolida el flujo diario asistencial, compila el PDF
    y lo despacha por correo SMTP.
    """
    logger.info("Iniciando tarea programada Celery: Consolidación y despacho de reporte diario.")
    try:
        historial = ReportFacade.enviar_reporte_diario_por_email()
        if not historial:
            resultado = "No se ejecutó despacho automático de reporte diario: sin destinatarios configurados."
            logger.info(resultado)
            return resultado

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
