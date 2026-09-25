"""
Generador de Documentos Oficiales PDF para Reportes Diarios con ReportLab.
Responsabilidad única: Renderizado y compilación de presentación visual en memoria.
"""
import io
from typing import Dict, Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


class ReportPdfGenerator:
    """
    Compila el reporte diario asistencial en formato PDF binario utilizando ReportLab.
    """

    @classmethod
    def generar(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Compila el reporte oficial en formato PDF en memoria a partir de un diccionario de métricas.
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


__all__ = ['ReportPdfGenerator']
