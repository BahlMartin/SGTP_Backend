"""
Servicio de Consolidación Diaria de Métricas Hospitalarias y Generación de Reporte PDF.
Utiliza ReportLab para compilar el informe en memoria y SMTP para el despacho a Jefa y Secretaría.
"""
import io
import logging
from typing import Dict, Any, List, Optional
from datetime import date, datetime, time
from django.utils import timezone
from django.core.mail import EmailMessage
from django.conf import settings
from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from app.models.user import Personal, RolPersonal
from app.models.box import AsignacionesBox
from app.models.ticket import Ticket, TicketEstudios, EstadoTicket
from app.models.report import HistorialReporteDiario

logger = logging.getLogger(__name__)


class ReportService:
    """
    Consolida la información del flujo asistencial diario y produce el documento oficial en PDF.
    """

    @classmethod
    def consolidar_metricas_diarias(cls, fecha_consulta: Optional[date] = None) -> Dict[str, Any]:
        """
        Consolida los indicadores asistenciales de una jornada (00:00 a 23:59 UTC).
        """
        if not fecha_consulta:
            fecha_consulta = timezone.now().date()

        inicio_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.min))
        fin_dia = timezone.make_aware(datetime.combine(fecha_consulta, time.max))

        # 1. Total de tickets emitidos en la jornada
        tickets_dia = Ticket.objects.filter(
            fecha_hora_admision__range=(inicio_dia, fin_dia),
            is_deleted=False
        )
        total_emitidos = tickets_dia.count()

        # 2. Total de tickets atendidos (Finalizados)
        total_atendidos = tickets_dia.filter(estado=EstadoTicket.FINALIZADO).count()

        # 3. Distribución por Clasificación de Triage
        distribucion_triage = list(
            tickets_dia.values('clasificacion_triage')
            .annotate(cantidad=Count('pk'))
            .order_by('-cantidad')
        )

        # 4. Asignaciones de la jornada para cálculo de tiempos
        asignaciones_dia = AsignacionesBox.objects.filter(
            fecha_hora_inicio__range=(inicio_dia, fin_dia)
        ).select_related('ticket', 'personal', 'box')

        # Tiempo promedio de espera (admisión -> inicio atención) en minutos
        tiempos_espera_minutos: List[float] = []
        for asig in asignaciones_dia:
            if asig.ticket and asig.ticket.fecha_hora_admision:
                diff = (asig.fecha_hora_inicio - asig.ticket.fecha_hora_admision).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_espera_minutos.append(diff)

        promedio_espera = (
            round(sum(tiempos_espera_minutos) / len(tiempos_espera_minutos), 1)
            if tiempos_espera_minutos else 0.0
        )

        # Tiempo promedio de atención (inicio -> fin) en minutos
        tiempos_atencion_minutos: List[float] = []
        for asig in asignaciones_dia:
            if asig.fecha_hora_final:
                diff = (asig.fecha_hora_final - asig.fecha_hora_inicio).total_seconds() / 60.0
                if diff >= 0:
                    tiempos_atencion_minutos.append(diff)

        promedio_atencion = (
            round(sum(tiempos_atencion_minutos) / len(tiempos_atencion_minutos), 1)
            if tiempos_atencion_minutos else 0.0
        )

        # 5. Pacientes atendidos por personal asistencial
        rendimiento_personal = list(
            asignaciones_dia.values(
                'personal__nombre',
                'personal__apellidos',
                'personal__rol',
                'personal__email'
            )
            .annotate(pacientes_atendidos=Count('id'))
            .order_by('-pacientes_atendidos')
        )

        # 6. Total de prácticas / estudios médicos solicitados
        total_estudios = TicketEstudios.objects.filter(
            ticket__in=tickets_dia
        ).count()

        return {
            'fecha': str(fecha_consulta),
            'total_emitidos': total_emitidos,
            'total_atendidos': total_atendidos,
            'distribucion_triage': distribucion_triage,
            'promedio_espera_minutos': promedio_espera,
            'promedio_atencion_minutos': promedio_atencion,
            'rendimiento_personal': rendimiento_personal,
            'total_estudios': total_estudios,
        }

    @classmethod
    def generar_pdf_reporte(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Compila el reporte oficial en formato PDF en memoria utilizando ReportLab.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        styles = getSampleStyleSheet()
        estilo_titulo = ParagraphStyle(
            'TituloReporte',
            parent=styles['Heading1'],
            fontSize=20,
            leading=24,
            textColor=colors.HexColor('#1E3A8A'),
            alignment=1
        )
        estilo_subtitulo = ParagraphStyle(
            'SubtituloReporte',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor('#4B5563'),
            alignment=1
        )
        estilo_encabezado_tabla = ParagraphStyle(
            'EncabezadoTabla',
            parent=styles['Normal'],
            fontSize=9,
            leading=11,
            fontName='Helvetica-Bold',
            textColor=colors.white,
            alignment=1
        )
        estilo_celda = ParagraphStyle(
            'CeldaTabla',
            parent=styles['Normal'],
            fontSize=9,
            leading=11,
            alignment=0
        )

        elementos = []

        # Título y metadatos
        elementos.append(Paragraph("SISTEMA DE GESTIÓN DE TRIAGE Y FLUJO DE PACIENTES (SGTP)", estilo_titulo))
        elementos.append(Paragraph(f"INFORME ASISTENCIAL DIARIO CONSOLIDADO - FECHA: {metricas['fecha']}", estilo_subtitulo))
        elementos.append(Spacer(1, 16))

        # Tarjetas de resumen general
        datos_resumen = [
            [
                Paragraph("<b>Total Pacientes Emitidos</b>", estilo_celda),
                Paragraph(str(metricas['total_emitidos']), estilo_celda),
                Paragraph("<b>Tiempo Promedio Espera</b>", estilo_celda),
                Paragraph(f"{metricas['promedio_espera_minutos']} min", estilo_celda),
            ],
            [
                Paragraph("<b>Total Pacientes Atendidos</b>", estilo_celda),
                Paragraph(str(metricas['total_atendidos']), estilo_celda),
                Paragraph("<b>Tiempo Promedio Atención</b>", estilo_celda),
                Paragraph(f"{metricas['promedio_atencion_minutos']} min", estilo_celda),
            ],
            [
                Paragraph("<b>Total Estudios Solicitados</b>", estilo_celda),
                Paragraph(str(metricas['total_estudios']), estilo_celda),
                Paragraph("<b>Fecha / Zona Horaria</b>", estilo_celda),
                Paragraph(f"{metricas['fecha']} (UTC)", estilo_celda),
            ]
        ]
        tabla_resumen = Table(datos_resumen, colWidths=[150, 100, 160, 130])
        tabla_resumen.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F4F6')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        elementos.append(tabla_resumen)
        elementos.append(Spacer(1, 16))

        # Distribución de Triage
        elementos.append(Paragraph("<b>1. Distribución por Categoría de Triage</b>", styles['Heading2']))
        tabla_triage_data = [
            [Paragraph("<b>Clasificación de Triage</b>", estilo_encabezado_tabla), Paragraph("<b>Cantidad de Pacientes</b>", estilo_encabezado_tabla)]
        ]
        for item in metricas.get('distribucion_triage', []):
            tabla_triage_data.append([
                Paragraph(str(item['clasificacion_triage']), estilo_celda),
                Paragraph(str(item['cantidad']), estilo_celda)
            ])
        if len(tabla_triage_data) == 1:
            tabla_triage_data.append([Paragraph("Sin datos registrados", estilo_celda), Paragraph("0", estilo_celda)])

        tabla_triage = Table(tabla_triage_data, colWidths=[350, 190])
        tabla_triage.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        elementos.append(tabla_triage)
        elementos.append(Spacer(1, 16))

        # Rendimiento por Personal
        elementos.append(Paragraph("<b>2. Rendimiento y Atención por Personal</b>", styles['Heading2']))
        tabla_personal_data = [
            [
                Paragraph("<b>Profesional</b>", estilo_encabezado_tabla),
                Paragraph("<b>Rol</b>", estilo_encabezado_tabla),
                Paragraph("<b>Email</b>", estilo_encabezado_tabla),
                Paragraph("<b>Atendidos</b>", estilo_encabezado_tabla)
            ]
        ]
        for p in metricas.get('rendimiento_personal', []):
            nombre_completo = f"{p['personal__apellidos']}, {p['personal__nombre']}"
            tabla_personal_data.append([
                Paragraph(nombre_completo, estilo_celda),
                Paragraph(str(p['personal__rol']), estilo_celda),
                Paragraph(str(p['personal__email']), estilo_celda),
                Paragraph(str(p['pacientes_atendidos']), estilo_celda),
            ])
        if len(tabla_personal_data) == 1:
            tabla_personal_data.append([
                Paragraph("Sin atenciones registradas", estilo_celda),
                Paragraph("-", estilo_celda),
                Paragraph("-", estilo_celda),
                Paragraph("0", estilo_celda)
            ])

        tabla_personal = Table(tabla_personal_data, colWidths=[180, 80, 200, 80])
        tabla_personal.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F766E')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        elementos.append(tabla_personal)

        # Construir documento
        doc.build(elementos)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    @classmethod
    def enviar_reporte_diario_por_email(cls, fecha_consulta: Optional[date] = None) -> HistorialReporteDiario:
        """
        Ejecuta la consolidación, genera el PDF y lo despacha vía SMTP a las cuentas de rol Jefa y Secretaria.
        """
        metricas = cls.consolidar_metricas_diarias(fecha_consulta)
        pdf_bytes = cls.generar_pdf_reporte(metricas)

        destinatarios = list(
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

        # Registrar en historial
        historial = HistorialReporteDiario.objects.create(
            fecha_reporte=datetime.strptime(fecha_str, '%Y-%m-%d').date(),
            total_pacientes_atendidos=metricas['total_atendidos'],
            total_estudios_realizados=metricas['total_estudios'],
            destinatarios_notificados=", ".join(destinatarios) if destinatarios else "Sin destinatarios",
            exitoso=exitoso,
            error_detalle=error_msg
        )
        return historial


ReportsService = ReportService

__all__ = ['ReportService', 'ReportsService']
