"""
Generador de Documentos Oficiales PDF para Reportes Diarios con ReportLab.
Responsabilidad única: Renderizado y compilación de presentación visual en memoria.
"""
import io
from typing import Dict, Any, List

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Canvas de doble pasada para calcular el número total de páginas (Página X de Y)
    e imprimir el pie de página institucional inalterable.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#64748B'))
        # Línea de pie de página
        self.setStrokeColor(colors.HexColor('#CBD5E1'))
        self.setLineWidth(0.5)
        self.line(36, 28, A4[0] - 36, 28)
        # Textos de pie
        self.drawString(36, 18, "SGTP Hospitalario | Documento Oficial Auditado")
        texto_pagina = f"Página {self._pageNumber} de {page_count}"
        self.drawRightString(A4[0] - 36, 18, texto_pagina)
        self.restoreState()


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
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=40
        )

        styles = getSampleStyleSheet()

        # Estilos tipográficos institucionales
        estilo_titulo = ParagraphStyle(
            'TituloDoc',
            parent=styles['Heading1'],
            fontSize=16,
            leading=20,
            textColor=colors.HexColor('#0F2F4A'),
            fontName='Helvetica-Bold',
            alignment=1
        )
        estilo_subtitulo = ParagraphStyle(
            'SubtituloDoc',
            parent=styles['Normal'],
            fontSize=10,
            leading=13,
            textColor=colors.HexColor('#475569'),
            alignment=1
        )
        estilo_seccion_h1 = ParagraphStyle(
            'SeccionH1',
            parent=styles['Heading2'],
            fontSize=12,
            leading=15,
            textColor=colors.HexColor('#0F2F4A'),
            fontName='Helvetica-Bold',
            spaceBefore=10,
            spaceAfter=6
        )
        estilo_seccion_h2 = ParagraphStyle(
            'SeccionH2',
            parent=styles['Heading3'],
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor('#0D9488'),
            fontName='Helvetica-Bold',
            spaceBefore=8,
            spaceAfter=4
        )
        estilo_encabezado_tabla = ParagraphStyle(
            'EncabezadoTabla',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            fontName='Helvetica-Bold',
            textColor=colors.white,
            alignment=1
        )
        estilo_celda = ParagraphStyle(
            'CeldaTabla',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#1E293B'),
            alignment=0
        )
        estilo_celda_centro = ParagraphStyle(
            'CeldaTablaCentro',
            parent=estilo_celda,
            alignment=1
        )
        estilo_celda_derecha = ParagraphStyle(
            'CeldaTablaDerecha',
            parent=estilo_celda,
            alignment=2
        )
        estilo_celda_bold = ParagraphStyle(
            'CeldaTablaBold',
            parent=estilo_celda,
            fontName='Helvetica-Bold'
        )

        ancho_util = 523  # A4 width (595) - 72pt margins

        elementos = []

        # ==============================================================================
        # CABECERA INSTITUCIONAL
        # ==============================================================================
        elementos.append(Paragraph("SISTEMA DE GESTIÓN DE TRIAGE Y FLUJO DE PACIENTES (SGTP)", estilo_titulo))
        elementos.append(Spacer(1, 2))
        elementos.append(Paragraph(
            f"INFORME ASISTENCIAL Y CLÍNICO CONSOLIDADO — JORNADA: <b>{metricas.get('fecha', 'N/D')}</b> (UTC)",
            estilo_subtitulo
        ))
        elementos.append(Spacer(1, 6))
        elementos.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0F2F4A'), spaceAfter=10))

        # ==============================================================================
        # PÁGINA 1: TABLERO EJECUTIVO GERENCIAL
        # ==============================================================================
        elementos.append(Paragraph("1. Resumen Ejecutivo y Métricas Clave de Flujo", estilo_seccion_h1))

        # Tarjetas KPI de alto nivel
        kpi_data = [
            [
                Paragraph("<b>Total Pacientes Emitidos:</b>", estilo_celda),
                Paragraph(f"<b>{metricas.get('total_emitidos', 0)}</b>", estilo_celda_centro),
                Paragraph("<b>Tiempo Promedio de Espera:</b>", estilo_celda),
                Paragraph(f"<b>{metricas.get('promedio_espera_minutos', 0)} min</b>", estilo_celda_centro),
            ],
            [
                Paragraph("<b>Total Pacientes Atendidos:</b>", estilo_celda),
                Paragraph(f"<font color='#0D9488'><b>{metricas.get('total_atendidos', 0)}</b></font>", estilo_celda_centro),
                Paragraph("<b>Tiempo Promedio de Atención:</b>", estilo_celda),
                Paragraph(f"<b>{metricas.get('promedio_atencion_minutos', 0)} min</b>", estilo_celda_centro),
            ],
            [
                Paragraph("<b>En Curso / Sala de Espera:</b>", estilo_celda),
                Paragraph(f"{metricas.get('total_en_curso', 0)}", estilo_celda_centro),
                Paragraph("<b>Tasa de Completitud:</b>", estilo_celda),
                Paragraph(f"{metricas.get('tasa_completitud_porcentaje', 0)}%", estilo_celda_centro),
            ],
            [
                Paragraph("<b>Cancelados / Deserción:</b>", estilo_celda),
                Paragraph(f"<font color='#E11D48'>{metricas.get('total_cancelados', 0)}</font>", estilo_celda_centro),
                Paragraph("<b>Tasa de Deserción (Drop-off):</b>", estilo_celda),
                Paragraph(f"<font color='#E11D48'>{metricas.get('tasa_desercion_porcentaje', 0)}%</font>", estilo_celda_centro),
            ],
            [
                Paragraph("<b>Total Estudios Realizados:</b>", estilo_celda),
                Paragraph(f"<b>{metricas.get('total_estudios', 0)}</b>", estilo_celda_centro),
                Paragraph("<b>Áreas con Estudios:</b>", estilo_celda),
                Paragraph(f"{len(metricas.get('resumen_secciones', []))} secciones", estilo_celda_centro),
            ]
        ]
        tabla_kpi = Table(kpi_data, colWidths=[150, 100, 160, 113])
        tabla_kpi.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#CBD5E1')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_kpi)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # FRANJAS HORARIAS HOSPITALARIAS
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("2. Distribución y Rendimiento por Franja Horaria (Turnos)", estilo_seccion_h1))
        tabla_franjas_data = [
            [
                Paragraph("<b>Turno / Franja</b>", estilo_encabezado_tabla),
                Paragraph("<b>Horario</b>", estilo_encabezado_tabla),
                Paragraph("<b>Emitidos</b>", estilo_encabezado_tabla),
                Paragraph("<b>Atendidos</b>", estilo_encabezado_tabla),
                Paragraph("<b>Cancelados</b>", estilo_encabezado_tabla),
                Paragraph("<b>Espera Prom.</b>", estilo_encabezado_tabla),
                Paragraph("<b>Atención Prom.</b>", estilo_encabezado_tabla),
            ]
        ]
        for f in metricas.get('franjas_horarias', []):
            tabla_franjas_data.append([
                Paragraph(f"<b>{f['nombre']}</b>", estilo_celda),
                Paragraph(f['rango_display'], estilo_celda_centro),
                Paragraph(str(f['total_emitidos']), estilo_celda_centro),
                Paragraph(str(f['total_atendidos']), estilo_celda_centro),
                Paragraph(str(f['total_cancelados']), estilo_celda_centro),
                Paragraph(f"{f['promedio_espera_minutos']} min", estilo_celda_centro),
                Paragraph(f"{f['promedio_atencion_minutos']} min", estilo_celda_centro),
            ])

        tabla_franjas = Table(tabla_franjas_data, colWidths=[140, 95, 55, 55, 55, 62, 61])
        tabla_franjas.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F2F4A')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_franjas)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # CUMPLIMIENTO ASISTENCIAL Y SLA DE TRIAGE
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("3. Triage Asistencial y Cumplimiento de Tiempos de Espera (SLA)", estilo_seccion_h1))
        tabla_sla_data = [
            [
                Paragraph("<b>Clasificación de Triage</b>", estilo_encabezado_tabla),
                Paragraph("<b>Total Pacientes</b>", estilo_encabezado_tabla),
                Paragraph("<b>Espera Promedio Real</b>", estilo_encabezado_tabla),
                Paragraph("<b>Prioridad / Estado</b>", estilo_encabezado_tabla),
            ]
        ]
        for s in metricas.get('sla_triage', []):
            if s['total_pacientes'] > 0 or s['clasificacion_triage'] in ['guardia', 'medicos', 'discapacidad']:
                # Indicador de prioridad
                if s['clasificacion_triage'] == 'guardia':
                    prio_text = "<font color='#DC2626'><b>Urgencia Inmediata</b></font>"
                elif s['clasificacion_triage'] == 'medicos':
                    prio_text = "<font color='#D97706'><b>Urgente</b></font>"
                elif s['clasificacion_triage'] in ['discapacidad', 'oncologia']:
                    prio_text = "<font color='#2563EB'><b>Prioritario</b></font>"
                else:
                    prio_text = "Demanda Ordinaria"

                tabla_sla_data.append([
                    Paragraph(f"<b>{s['nombre_display']}</b>", estilo_celda),
                    Paragraph(str(s['total_pacientes']), estilo_celda_centro),
                    Paragraph(f"<b>{s['promedio_espera_minutos']} min</b>", estilo_celda_centro),
                    Paragraph(prio_text, estilo_celda_centro),
                ])

        tabla_sla = Table(tabla_sla_data, colWidths=[200, 95, 115, 113])
        tabla_sla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F766E')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_sla)

        # ==============================================================================
        # PÁGINA 2+: INFORME DE LABORATORIO BIOQUÍMICO (JEFA DE LABORATORIO)
        # ==============================================================================
        elementos.append(PageBreak())
        elementos.append(Paragraph("4. Resumen Consolidado por Sección de Laboratorio", estilo_seccion_h1))

        resumen_sec = metricas.get('resumen_secciones', [])
        tabla_sec_data = [
            [
                Paragraph("<b>Sección / Área de Laboratorio</b>", estilo_encabezado_tabla),
                Paragraph("<b>Total Estudios Realizados</b>", estilo_encabezado_tabla),
                Paragraph("<b>Porcentaje del Total</b>", estilo_encabezado_tabla),
            ]
        ]
        for s in resumen_sec:
            tabla_sec_data.append([
                Paragraph(f"<b>{s['nombre_seccion']}</b>", estilo_celda),
                Paragraph(f"<b>{s['total_estudios']}</b>", estilo_celda_centro),
                Paragraph(f"{s['porcentaje']}%", estilo_celda_centro),
            ])
        if len(tabla_sec_data) == 1:
            tabla_sec_data.append([Paragraph("Sin estudios registrados en la jornada", estilo_celda), Paragraph("0", estilo_celda_centro), Paragraph("0%", estilo_celda_centro)])

        tabla_sec = Table(tabla_sec_data, colWidths=[263, 130, 130])
        tabla_sec.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_sec)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # LOGÍSTICA DE INSUMOS Y TUBOS POR TIPO DE MUESTRA
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("5. Logística de Muestras e Insumos Requeridos", estilo_seccion_h1))
        insumos = metricas.get('insumos_tubos', [])
        tabla_insumos_data = [
            [
                Paragraph("<b>Tipo de Muestra / Insumo Requerido</b>", estilo_encabezado_tabla),
                Paragraph("<b>Unidades Requeridas</b>", estilo_encabezado_tabla),
                Paragraph("<b>Proporción</b>", estilo_encabezado_tabla),
            ]
        ]
        for ins in insumos:
            tabla_insumos_data.append([
                Paragraph(f"<b>{ins['descripcion_tubo']}</b>", estilo_celda),
                Paragraph(f"<b>{ins['total_tubos']}</b>", estilo_celda_centro),
                Paragraph(f"{ins['porcentaje']}%", estilo_celda_centro),
            ])
        if len(tabla_insumos_data) == 1:
            tabla_insumos_data.append([Paragraph("Sin insumos requeridos", estilo_celda), Paragraph("0", estilo_celda_centro), Paragraph("0%", estilo_celda_centro)])

        tabla_insumos = Table(tabla_insumos_data, colWidths=[263, 130, 130])
        tabla_insumos.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F766E')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_insumos)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # AUDITORÍA DE CALIDAD Y DISCREPANCIAS DE BOX
        # ------------------------------------------------------------------------------
        auditoria = metricas.get('auditoria_box', {})
        elementos.append(Paragraph("6. Auditoría de Calidad y Modificaciones en Box de Extracción", estilo_seccion_h1))
        tabla_auditoria_data = [
            [
                Paragraph("<b>Cargados en Admisión</b>", estilo_encabezado_tabla),
                Paragraph("<b>Agregados en Box</b>", estilo_encabezado_tabla),
                Paragraph("<b>Cancelados en Box</b>", estilo_encabezado_tabla),
                Paragraph("<b>Tasa Rectificación Box</b>", estilo_encabezado_tabla),
            ],
            [
                Paragraph(str(auditoria.get('total_cargados_admision', 0)), estilo_celda_centro),
                Paragraph(f"<font color='#0D9488'><b>+{auditoria.get('total_agregados_box', 0)}</b></font>", estilo_celda_centro),
                Paragraph(f"<font color='#E11D48'><b>-{auditoria.get('total_cancelados_box', 0)}</b></font>", estilo_celda_centro),
                Paragraph(f"<b>{auditoria.get('tasa_rectificacion_porcentaje', 0.0)}%</b>", estilo_celda_centro),
            ]
        ]
        tabla_auditoria = Table(tabla_auditoria_data, colWidths=[130, 131, 131, 131])
        tabla_auditoria.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#334155')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        elementos.append(tabla_auditoria)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # DETALLE COMPLETO DE TODAS LAS PRÁCTICAS MÉDICAS POR SECCIÓN
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("7. Detalle Exhaustivo de Prácticas Médicas por Sección", estilo_seccion_h1))
        elementos.append(Paragraph(
            "Nómina completa de todos los estudios clínicos procesados durante la jornada asistencial agrupados por su sección correspondiente.",
            estilo_celda
        ))
        elementos.append(Spacer(1, 6))

        if not resumen_sec:
            elementos.append(Paragraph("<i>No se realizaron prácticas médicas en la jornada seleccionada.</i>", estilo_celda))
        else:
            for sec in resumen_sec:
                practicas_sec = sec.get('practicas', [])
                if not practicas_sec:
                    continue

                # Encabezado de sección
                elementos.append(Paragraph(f"• Sección {sec['nombre_seccion']} ({sec['total_estudios']} estudios)", estilo_seccion_h2))

                tabla_p_data = [
                    [
                        Paragraph("<b>Cód.</b>", estilo_encabezado_tabla),
                        Paragraph("<b>Práctica / Estudio Clínico</b>", estilo_encabezado_tabla),
                        Paragraph("<b>Muestra Requerida</b>", estilo_encabezado_tabla),
                        Paragraph("<b>Cantidad Realizada</b>", estilo_encabezado_tabla),
                    ]
                ]
                for pr in practicas_sec:
                    tabla_p_data.append([
                        Paragraph(str(pr['codigo'] or '—'), estilo_celda),
                        Paragraph(str(pr['nombre']), estilo_celda),
                        Paragraph(str(pr['tipo_muestra']).capitalize(), estilo_celda_centro),
                        Paragraph(f"<b>{pr['total']}</b>", estilo_celda_centro),
                    ])

                tabla_p = Table(tabla_p_data, colWidths=[65, 258, 110, 90])
                tabla_p.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
                    ('PADDING', (0, 0), (-1, -1), 3),
                ]))
                elementos.append(tabla_p)
                elementos.append(Spacer(1, 6))

        # ==============================================================================
        # PÁGINA 3+: RENDIMIENTO Y PRODUCTIVIDAD DE PERSONAL POR ÁREA
        # ==============================================================================
        elementos.append(PageBreak())
        elementos.append(Paragraph("8. Rendimiento y Productividad del Personal Asistencial", estilo_seccion_h1))

        # ------------------------------------------------------------------------------
        # SUB-ÁREA: ADMISIÓN (ORDENADO DE MAYOR A MENOR)
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("A. Operadores de Admisión (Ordenados por Pacientes Recepcionados)", estilo_seccion_h2))
        admision_data = [
            [
                Paragraph("<b>Operador / Profesional</b>", estilo_encabezado_tabla),
                Paragraph("<b>Matrícula / DNI</b>", estilo_encabezado_tabla),
                Paragraph("<b>Correo Institucional</b>", estilo_encabezado_tabla),
                Paragraph("<b>Tickets Emitidos</b>", estilo_encabezado_tabla),
            ]
        ]
        for adm in metricas.get('rendimiento_admision', []):
            mat = adm.get('personal_admision__matricula') or f"DNI {adm.get('personal_admision__dni', '—')}"
            admision_data.append([
                Paragraph(f"<b>{adm['nombre_completo']}</b>", estilo_celda),
                Paragraph(str(mat), estilo_celda_centro),
                Paragraph(str(adm.get('personal_admision__email', '—')), estilo_celda),
                Paragraph(f"<b>{adm['pacientes_recepcionados']}</b>", estilo_celda_centro),
            ])
        if len(admision_data) == 1:
            admision_data.append([Paragraph("Sin emisiones registradas", estilo_celda), Paragraph("—", estilo_celda_centro), Paragraph("—", estilo_celda), Paragraph("0", estilo_celda_centro)])

        tabla_adm = Table(admision_data, colWidths=[173, 100, 150, 100])
        tabla_adm.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F2F4A')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_adm)
        elementos.append(Spacer(1, 10))

        # ------------------------------------------------------------------------------
        # SUB-ÁREA: BOXES DE EXTRACCIÓN (ORDENADO DE MAYOR A MENOR + TIEMPO PROMEDIO)
        # ------------------------------------------------------------------------------
        elementos.append(Paragraph("B. Técnicos de Box de Extracción (Ordenados por Pacientes Atendidos)", estilo_seccion_h2))
        box_data = [
            [
                Paragraph("<b>Técnico / Profesional</b>", estilo_encabezado_tabla),
                Paragraph("<b>Matrícula</b>", estilo_encabezado_tabla),
                Paragraph("<b>Correo Institucional</b>", estilo_encabezado_tabla),
                Paragraph("<b>Atendidos</b>", estilo_encabezado_tabla),
                Paragraph("<b>Ausentes</b>", estilo_encabezado_tabla),
                Paragraph("<b>Tiempo Promedio</b>", estilo_encabezado_tabla),
            ]
        ]
        for bx in metricas.get('rendimiento_box', []):
            box_data.append([
                Paragraph(f"<b>{bx['nombre_completo']}</b>", estilo_celda),
                Paragraph(str(bx['matricula']), estilo_celda_centro),
                Paragraph(str(bx['email']), estilo_celda),
                Paragraph(f"<font color='#0D9488'><b>{bx['pacientes_atendidos']}</b></font>", estilo_celda_centro),
                Paragraph(f"<font color='#E11D48'><b>{bx.get('pacientes_ausentes', 0)}</b></font>", estilo_celda_centro),
                Paragraph(f"{bx['promedio_atencion_minutos']} min", estilo_celda_centro),
            ])
        if len(box_data) == 1:
            box_data.append([Paragraph("Sin atenciones registradas en box", estilo_celda), Paragraph("—", estilo_celda_centro), Paragraph("—", estilo_celda), Paragraph("0", estilo_celda_centro), Paragraph("0", estilo_celda_centro), Paragraph("—", estilo_celda_centro)])

        tabla_bx = Table(box_data, colWidths=[135, 65, 128, 65, 65, 65])
        tabla_bx.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0D9488')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        elementos.append(tabla_bx)

        # Construir documento utilizando NumberedCanvas para paginación precisa
        doc.build(elementos, canvasmaker=NumberedCanvas)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes


__all__ = ['ReportPdfGenerator', 'NumberedCanvas']
