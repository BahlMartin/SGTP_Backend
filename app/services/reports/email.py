"""
Servicio especializado en el despacho de reportes por correo electrónico (SMTP) y auditoría.
Responsabilidad única: notificaciones asistenciales y registro inalterable de auditoría.

El transporte SMTP se configura por variables de entorno (hoy: Brevo, plan gratuito).
El cuerpo se envía en HTML con alternativa en texto plano; los gráficos son tablas HTML
con anchos porcentuales (sin imágenes ni JavaScript) para que se vean en cualquier cliente.
"""
import logging
from typing import Any, Dict, List
from datetime import datetime
from xml.sax.saxutils import escape

from django.core.mail import EmailMultiAlternatives
from django.conf import settings

from app.models.user import Personal, RolPersonal
from app.models.report import HistorialReporteDiario
from app.services.reports.pdf import (
    INSTITUCION,
    OBJETIVO_ESPERA_GENERAL_MIN,
    ReportPdfGenerator,
    _dec,
    _fecha_local,
    _n,
    _pct,
)

logger = logging.getLogger(__name__)

COLOR_TEAL = '#0f766e'


def _barra_html(porcentaje: float, color: str) -> str:
    """Barra horizontal hecha con tabla: compatible con Gmail, Outlook y móviles."""
    ancho = 0 if porcentaje <= 0 else max(2, min(100, round(porcentaje)))
    relleno = (
        f'<td width="{ancho}%" height="10" bgcolor="{color}" '
        f'style="font-size:1px;line-height:10px;border-radius:5px;">&nbsp;</td>'
        if ancho else ''
    )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f1f5f9" '
        f'style="border-radius:5px;"><tr>{relleno}<td height="10" style="font-size:1px;line-height:10px;">&nbsp;</td></tr></table>'
    )


def _fila_barra_html(etiqueta: str, porcentaje_barra: float, color: str, valor: str) -> str:
    return (
        '<tr>'
        f'<td width="130" style="font-size:12px;color:#334155;padding:4px 0;">{escape(etiqueta)}</td>'
        f'<td style="padding:4px 8px;">{_barra_html(porcentaje_barra, color)}</td>'
        f'<td width="80" align="right" style="font-size:12px;color:#0f172a;font-weight:700;padding:4px 0;white-space:nowrap;">{escape(valor)}</td>'
        '</tr>'
    )


def _kpi_html(etiqueta: str, valor: str, color: str = '#0f172a') -> str:
    return (
        '<td width="50%" valign="top" style="padding:5px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="border:1px solid #e2e8f0;border-radius:8px;"><tr><td style="padding:10px 12px;">'
        f'<div style="font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748b;font-weight:700;">{escape(etiqueta)}</div>'
        f'<div style="font-size:24px;font-weight:800;color:{color};line-height:30px;">{escape(valor)}</div>'
        '</td></tr></table></td>'
    )


def construir_contenido_correo(metricas: Dict[str, Any]) -> Dict[str, str]:
    """
    Devuelve asunto, cuerpo en texto plano y cuerpo HTML del correo de informe diario.
    """
    fecha_txt = _fecha_local(metricas.get('fecha', ''))
    asunto = f"[SGTP] Informe diario de actividad · {fecha_txt}"

    filas_triage, total_triage = ReportPdfGenerator._filas_triage(metricas)
    maximo_triage = max([f['cantidad'] for f in filas_triage] + [1])

    secciones = sorted(
        metricas.get('resumen_secciones', []), key=lambda s: s.get('total_estudios', 0), reverse=True
    )[:3]
    maximo_sec = max([int(s.get('total_estudios', 0)) for s in secciones] + [1])

    # Objetivos de espera excedidos
    sla = {s['clasificacion_triage']: s for s in metricas.get('sla_triage', [])}
    excedidos: List[str] = []
    for fila in filas_triage:
        item = sla.get(fila['key'])
        if fila['objetivo'] is None or not item or not item.get('total_pacientes'):
            continue
        espera = float(item.get('promedio_espera_minutos', 0) or 0)
        if espera > fila['objetivo']:
            excedidos.append(
                f"La espera de «{fila['label']}» ({_dec(espera, 0)} min) superó el objetivo de {_dec(fila['objetivo'], 0)} min."
            )

    espera_general = float(metricas.get('promedio_espera_minutos', 0) or 0)
    kpis = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:10px -5px;">'
        '<tr>'
        + _kpi_html('Atendidos', _n(metricas.get('total_atendidos', 0)))
        + _kpi_html('Estudios', _n(metricas.get('total_estudios', 0)))
        + '</tr><tr>'
        + _kpi_html('Espera promedio', f"{_dec(espera_general)} min")
        + _kpi_html('Críticos', _n(metricas.get('total_criticos_atendidos', 0)), '#b91c1c')
        + '</tr></table>'
    )

    triage_html = ''.join(
        _fila_barra_html(
            f['label'], 100 * f['cantidad'] / maximo_triage, f['color'],
            f"{_n(f['cantidad'])} · {_pct(f['cantidad'], total_triage)}",
        )
        for f in filas_triage
    )
    secciones_html = ''.join(
        _fila_barra_html(
            s['nombre_seccion'], 100 * int(s['total_estudios']) / maximo_sec, COLOR_TEAL, _n(s['total_estudios'])
        )
        for s in secciones
    ) or '<tr><td style="font-size:12px;color:#64748b;">Sin estudios registrados en la jornada.</td></tr>'

    alerta_html = ''.join(
        '<p style="margin:12px 0 0;background:#fef2f2;border-left:3px solid #b91c1c;padding:8px 10px;'
        f'color:#991b1b;font-size:12px;">⚠ {escape(txt)}</p>'
        for txt in excedidos
    )

    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f1f5f9"><tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;">
  <tr><td bgcolor="{COLOR_TEAL}" style="background:{COLOR_TEAL};padding:20px 24px;color:#ffffff;">
    <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;opacity:.85;">{escape(INSTITUCION)}</div>
    <div style="font-size:20px;font-weight:700;margin-top:4px;">Informe diario · {escape(fecha_txt)}</div>
  </td></tr>
  <tr><td style="padding:20px 24px;font-size:13px;line-height:20px;color:#334155;">
    Hola, te compartimos el resumen de la jornada. El informe completo está adjunto en PDF.
    {kpis}
    <div style="font-size:13px;font-weight:700;color:#0f172a;margin:16px 0 4px;">Pacientes por triage</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{triage_html}</table>
    <div style="font-size:13px;font-weight:700;color:#0f172a;margin:18px 0 4px;">Secciones con más estudios</div>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{secciones_html}</table>
    {alerta_html}
    <p style="margin:18px 0 0;background:#0f172a;color:#ffffff;padding:11px 16px;border-radius:8px;font-weight:700;font-size:13px;text-align:center;">
      📎 Informe completo adjunto (PDF)
    </p>
  </td></tr>
  <tr><td bgcolor="#f8fafc" style="padding:14px 24px;border-top:1px solid #e2e8f0;color:#64748b;font-size:11px;line-height:16px;">
    Correo generado automáticamente por SGTP. Horario: Argentina (UTC-3). Contiene información confidencial.
  </td></tr>
</table></td></tr></table></body></html>"""

    lineas_triage = '\n'.join(
        f"  - {f['label']}: {_n(f['cantidad'])} ({_pct(f['cantidad'], total_triage)})" for f in filas_triage
    )
    texto = (
        f"Hola,\n\n"
        f"Te compartimos el informe diario de actividad de {INSTITUCION} correspondiente al {fecha_txt}. "
        f"El informe completo está adjunto en PDF.\n\n"
        f"Resumen:\n"
        f"- Pacientes atendidos: {_n(metricas.get('total_atendidos', 0))} de {_n(metricas.get('total_emitidos', 0))} ingresos\n"
        f"- Estudios realizados: {_n(metricas.get('total_estudios', 0))}\n"
        f"- Espera promedio: {_dec(espera_general)} min (objetivo {OBJETIVO_ESPERA_GENERAL_MIN} min)\n"
        f"- Atención promedio: {_dec(metricas.get('promedio_atencion_minutos', 0))} min\n"
        f"- Críticos atendidos: {_n(metricas.get('total_criticos_atendidos', 0))}\n\n"
        f"Pacientes por triage:\n{lineas_triage}\n"
        + ('\n' + '\n'.join(f"Aviso: {t}" for t in excedidos) + '\n' if excedidos else '')
        + "\nCorreo generado automáticamente por SGTP (horario de Argentina). Contiene información confidencial."
    )
    return {'asunto': asunto, 'texto': texto, 'html': html}


class ReportEmailService:
    """
    Gestiona el envío del reporte diario por SMTP a las autoridades y la auditoría del proceso.
    """

    @classmethod
    def despachar(
        cls,
        metricas: Dict[str, Any],
        pdf_bytes: bytes,
        destinatarios: list[str] | None = None
    ) -> HistorialReporteDiario | None:
        """
        Envía por correo el PDF a los destinatarios especificados (usuario logeado)
        y registra la auditoría. Si no se proveen destinatarios, no envía correo y retorna None.
        """
        if not destinatarios:
            logger.warning("No se especificaron destinatarios para el reporte. Despacho cancelado.")
            return None

        destinatarios_validos: List[str] = [
            d.strip() for d in destinatarios if isinstance(d, str) and d.strip()
        ]
        if not destinatarios_validos:
            logger.warning("Lista de destinatarios vacía. Despacho cancelado.")
            return None

        fecha_str = metricas['fecha']
        contenido = construir_contenido_correo(metricas)

        exitoso = True
        error_msg = ''

        try:
            email = EmailMultiAlternatives(
                subject=contenido['asunto'],
                body=contenido['texto'],
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=destinatarios_validos,
            )
            email.attach_alternative(contenido['html'], 'text/html')
            email.attach(f"Informe_Diario_SGTP_{fecha_str}.pdf", pdf_bytes, 'application/pdf')
            email.send(fail_silently=False)
        except Exception as e:
            logger.error("Error al despachar el correo SMTP del reporte diario: %s", e)
            exitoso = False
            error_msg = str(e)

        # Registrar trazabilidad en el modelo de auditoría
        historial = HistorialReporteDiario.objects.create(
            fecha_reporte=datetime.strptime(fecha_str, '%Y-%m-%d').date(),
            total_pacientes_atendidos=metricas['total_atendidos'],
            total_estudios_realizados=metricas['total_estudios'],
            destinatarios_notificados=", ".join(destinatarios_validos),
            exitoso=exitoso,
            error_detalle=error_msg
        )
        return historial


__all__ = ['ReportEmailService', 'construir_contenido_correo']
