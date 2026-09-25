"""
Servicio especializado en el despacho de reportes por correo electrónico (SMTP) y auditoría.
Responsabilidad única: Notificaciones asistenciales y registro inalterable de auditoría.
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

from django.core.mail import EmailMessage
from django.conf import settings

from app.models.user import Personal, RolPersonal
from app.models.report import HistorialReporteDiario

logger = logging.getLogger(__name__)


class ReportEmailService:
    """
    Gestiona el envío del reporte diario por SMTP a las autoridades y la auditoría del proceso.
    """

    @classmethod
    def despachar(cls, metricas: Dict[str, Any], pdf_bytes: bytes) -> HistorialReporteDiario:
        """
        Envía por correo el PDF a los roles autorizados (Jefa y Secretaria) y registra la transacción.
        """
        destinatarios: List[str] = list(
            Personal.objects.filter(
                rol__in=[RolPersonal.JEFA, RolPersonal.SECRETARIA],
                activo=True
            ).values_list('email', flat=True)
        )

        fecha_str = metricas['fecha']
        asunto = f"[SGTP Hospitalario] Reporte Asistencial Consolidado - {fecha_str}"
        cuerpo = (
            f"Estimadas autoridades y secretaría:\n\n"
            f"Se adjunta el reporte diario consolidado de atención asistencial del SGTP correspondiente al día {fecha_str} (UTC).\n\n"
            f"Resumen Ejecutivo:\n"
            f"- Total de pacientes emitidos: {metricas['total_emitidos']}\n"
            f"- Total de pacientes atendidos: {metricas['total_atendidos']}\n"
            f"- Tiempo promedio de espera: {metricas['promedio_espera_minutos']} min\n"
            f"- Tiempo promedio de atención: {metricas['promedio_atencion_minutos']} min\n"
            f"- Estudios médicos solicitados: {metricas['total_estudios']}\n\n"
            "Este correo y su archivo adjunto son generados automáticamente por el sistema."
        )

        exitoso = True
        error_msg = ''

        if destinatarios:
            try:
                email = EmailMessage(
                    subject=asunto,
                    body=cuerpo,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=destinatarios,
                )
                email.attach(f"Reporte_Diario_SGTP_{fecha_str}.pdf", pdf_bytes, 'application/pdf')
                email.send(fail_silently=False)
            except Exception as e:
                logger.error("Error al despachar el correo SMTP del reporte diario: %s", e)
                exitoso = False
                error_msg = str(e)
        else:
            error_msg = "No se encontraron usuarios activos con rol 'Jefa' o 'Secretaria' para notificar."

        # Registrar trazabilidad en el modelo de auditoría
        historial = HistorialReporteDiario.objects.create(
            fecha_reporte=datetime.strptime(fecha_str, '%Y-%m-%d').date(),
            total_pacientes_atendidos=metricas['total_atendidos'],
            total_estudios_realizados=metricas['total_estudios'],
            destinatarios_notificados=", ".join(destinatarios) if destinatarios else "Sin destinatarios",
            exitoso=exitoso,
            error_detalle=error_msg
        )
        return historial


__all__ = ['ReportEmailService']
