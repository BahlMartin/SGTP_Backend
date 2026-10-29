"""
Generador del informe diario en PDF (ReportLab).
Responsabilidad única: renderizado visual en memoria a partir de las métricas consolidadas.

Estructura del documento:
  - Página 1: resumen de la jornada (KPIs + gráficos de triage, secciones y muestras).
  - Página 2: cumplimiento de tiempos, franjas horarias y auditoría de box.
  - Anexo: detalle por sección, insumos, prácticas y rendimiento del personal.
"""
import io
from datetime import datetime
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ==============================================================================
# Identidad visual y parámetros fijos
# ==============================================================================
INSTITUCION = "Laboratorio de Análisis Clínicos"
TITULO_INFORME = "Informe diario de actividad"
LOGO_TEXTO = "SGTP"

COLOR_TEAL = colors.HexColor('#0F766E')
COLOR_TEAL_CLARO = colors.HexColor('#5EEAD4')
COLOR_TEXTO = colors.HexColor('#0F172A')
COLOR_SECUNDARIO = colors.HexColor('#64748B')
COLOR_BORDE = colors.HexColor('#E2E8F0')
COLOR_FONDO_SUAVE = colors.HexColor('#F1F5F9')
COLOR_ROJO = colors.HexColor('#B91C1C')

ANCHO_PAGINA, ALTO_PAGINA = A4
MARGEN = 36
ANCHO_UTIL = ANCHO_PAGINA - 2 * MARGEN  # 523 pt

# Objetivo general de espera (minutos) usado en la lectura rápida de la portada.
OBJETIVO_ESPERA_GENERAL_MIN = 15

# Categorías de triage: etiqueta corta, color de la app y objetivo de espera (min).
# Clave = valor de ClasificacionTriage.
TRIAGE_META: List[Tuple[str, str, str, float | None]] = [
    ('guardia', 'Guardia', '#EF4444', 5),
    ('medicos', 'Médicos', '#F97316', 10),
    ('discapacidad', 'Discapacidad', '#EAB308', 10),
    ('oncologia', 'Oncología', '#0284C7', 15),
    ('extraccion con turno', 'Extracción con turno', '#22C55E', 15),
    ('extraccion sin turno', 'Extracción sin turno', '#A855F7', 30),
    ('otro', 'Otro', '#64748B', None),
]

# Tipos de muestra agrupados como en la pantalla de Secretaría.
MUESTRAS_SANGRE = {'edta', 'citrato', 'suero', 'jeringa', 'sangre'}
MUESTRAS_ESTILO = [
    ('sangre', 'Sangre', '#0F766E'),
    ('orina', 'Orina', '#4338CA'),
    ('materia fecal', 'Materia fecal', '#B45309'),
    ('otros', 'Otros', '#64748B'),
]


# ==============================================================================
# Utilidades de formato
# ==============================================================================
def _n(valor: Any) -> str:
    """1234 -> '1.234'."""
    try:
        return f"{int(valor or 0):,}".replace(',', '.')
    except (TypeError, ValueError):
        return "0"


def _dec(valor: Any, decimales: int = 1) -> str:
    """18.3 -> '18,3'."""
    try:
        return f"{float(valor or 0):.{decimales}f}".replace('.', ',')
    except (TypeError, ValueError):
        return "0,0"


def _pct(parte: float, total: float) -> str:
    return f"{_dec((parte / total) * 100 if total else 0)}%"


def _fecha_local(fecha_iso: str) -> str:
    if not fecha_iso:
        return 'N/D'
    texto = str(fecha_iso).strip()
    if ' al ' in texto:
        partes = texto.split(' al ', 1)
        return f"{_fecha_local(partes[0].strip())} - {_fecha_local(partes[1].strip())}"
    try:
        return datetime.strptime(texto, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return texto


def _truncar(texto: str, fuente: str, tam: float, ancho_max: float) -> str:
    if stringWidth(texto, fuente, tam) <= ancho_max:
        return texto
    while texto and stringWidth(texto + '…', fuente, tam) > ancho_max:
        texto = texto[:-1]
    return texto.rstrip() + '…'


def _esc(valor: Any) -> str:
    return escape(str(valor if valor is not None else ''))


# ==============================================================================
# Canvas: pie de página "Página X de Y"
# ==============================================================================
class NumberedCanvas(canvas.Canvas):
    """
    Canvas de doble pasada para calcular el número total de páginas (Página X de Y)
    e imprimir el pie de página institucional.
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
        self.setFillColor(COLOR_SECUNDARIO)
        self.setStrokeColor(colors.HexColor('#CBD5E1'))
        self.setLineWidth(0.5)
        self.line(MARGEN, 28, ANCHO_PAGINA - MARGEN, 28)
        self.drawString(MARGEN, 18, "SGTP · Informe confidencial de uso interno")
        self.drawRightString(ANCHO_PAGINA - MARGEN, 18, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


# ==============================================================================
# Gráficos vectoriales (ReportLab Graphics)
# ==============================================================================
def _grafico_triage(filas: List[Dict[str, Any]], total: int, ancho: float = ANCHO_UTIL) -> Drawing:
    """Barras horizontales por prioridad con cantidad y porcentaje."""
    alto_fila = 17
    alto = alto_fila * len(filas) + 2
    d = Drawing(ancho, alto)
    x_pista, ancho_pista = 128, ancho - 128 - 70
    maximo = max([f['cantidad'] for f in filas] + [1])
    for i, f in enumerate(filas):
        y = alto - (i + 1) * alto_fila + 5
        d.add(String(0, y + 0.5, f['label'], fontName='Helvetica', fontSize=8.5, fillColor=COLOR_TEXTO))
        d.add(Rect(x_pista, y, ancho_pista, 8, rx=4, ry=4, fillColor=COLOR_FONDO_SUAVE, strokeColor=None))
        if f['cantidad'] > 0:
            largo = max(8, ancho_pista * f['cantidad'] / maximo)
            d.add(Rect(x_pista, y, largo, 8, rx=4, ry=4, fillColor=colors.HexColor(f['color']), strokeColor=None))
        d.add(String(ancho - 40, y + 0.5, _n(f['cantidad']), fontName='Helvetica-Bold', fontSize=8.5,
                     fillColor=COLOR_TEXTO, textAnchor='end'))
        d.add(String(ancho, y + 0.5, _pct(f['cantidad'], total), fontName='Helvetica', fontSize=8,
                     fillColor=COLOR_SECUNDARIO, textAnchor='end'))
    return d


def _grafico_lollipop(items: List[Tuple[str, int]], ancho: float) -> Drawing:
    """Lollipop (línea + punto) de estudios por sección."""
    alto_fila = 17
    alto = alto_fila * len(items) + 2
    d = Drawing(ancho, alto)
    x0, largo_max = 104, ancho - 104 - 26
    maximo = max([v for _, v in items] + [1])
    for i, (nombre, valor) in enumerate(items):
        y = alto - (i + 1) * alto_fila + 5
        d.add(String(0, y + 0.5, _truncar(nombre, 'Helvetica', 8, 98), fontName='Helvetica', fontSize=8,
                     fillColor=COLOR_TEXTO))
        d.add(Line(x0, y + 4, x0 + largo_max, y + 4, strokeColor=COLOR_BORDE, strokeWidth=0.6))
        largo = largo_max * valor / maximo
        d.add(Line(x0, y + 4, x0 + largo, y + 4, strokeColor=COLOR_TEAL_CLARO, strokeWidth=1.6))
        d.add(Circle(x0 + largo, y + 4, 4, fillColor=COLOR_TEAL, strokeColor=colors.white, strokeWidth=1))
        d.add(String(ancho, y + 0.5, _n(valor), fontName='Helvetica-Bold', fontSize=8, fillColor=COLOR_TEXTO,
                     textAnchor='end'))
    return d


def _grafico_columnas(items: List[Dict[str, Any]], ancho: float, alto: float = 128,
                      ancho_barra: float = 34, alto_max_barra: float = 70) -> Drawing:
    """Barras verticales con valor arriba y nombre + porcentaje debajo."""
    d = Drawing(ancho, alto)
    base_y = 30
    total = sum(i['valor'] for i in items)
    maximo = max([i['valor'] for i in items] + [1])
    slot = ancho / max(len(items), 1)
    for idx, it in enumerate(items):
        cx = slot * idx + slot / 2
        h = max(2, alto_max_barra * it['valor'] / maximo) if it['valor'] else 1
        d.add(Rect(cx - ancho_barra / 2, base_y, ancho_barra, h, fillColor=colors.HexColor(it['color']),
                   strokeColor=None))
        d.add(String(cx, base_y + h + 4, _n(it['valor']), fontName='Helvetica-Bold', fontSize=9,
                     fillColor=COLOR_TEXTO, textAnchor='middle'))
        d.add(String(cx, base_y - 11, _truncar(it['label'], 'Helvetica-Bold', 7.5, slot - 4),
                     fontName='Helvetica-Bold', fontSize=7.5, fillColor=COLOR_TEXTO, textAnchor='middle'))
        d.add(String(cx, base_y - 21, _pct(it['valor'], total), fontName='Helvetica', fontSize=7,
                     fillColor=COLOR_SECUNDARIO, textAnchor='middle'))
    d.add(Line(0, base_y, ancho, base_y, strokeColor=colors.HexColor('#CBD5E1'), strokeWidth=0.6))
    return d


# ==============================================================================
# Generador principal
# ==============================================================================
class ReportPdfGenerator:
    """
    Compila el informe diario asistencial en formato PDF binario utilizando ReportLab.
    """

    @staticmethod
    def _estilos() -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()['Normal']
        return {
            'titulo': ParagraphStyle('Titulo', parent=base, fontName='Helvetica-Bold', fontSize=15, leading=18,
                                     textColor=COLOR_TEXTO),
            'subtitulo': ParagraphStyle('Subtitulo', parent=base, fontSize=9, leading=12, textColor=COLOR_SECUNDARIO),
            'h3': ParagraphStyle('H3', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=13,
                                 textColor=COLOR_TEXTO),
            'h3_der': ParagraphStyle('H3Der', parent=base, fontName='Helvetica-Bold', fontSize=10.5, leading=13,
                                     textColor=COLOR_TEAL, alignment=2),
            'celda': ParagraphStyle('Celda', parent=base, fontSize=8, leading=10, textColor=colors.HexColor('#1E293B'),
                                    keepWithNext=0),
            'celda_sec': ParagraphStyle('CeldaSec', parent=base, fontSize=8, leading=10,
                                        textColor=colors.HexColor('#1E293B'), keepWithNext=1),
            'celda_der': ParagraphStyle('CeldaDer', parent=base, fontSize=8, leading=10,
                                        textColor=colors.HexColor('#1E293B'), alignment=2),
            'th': ParagraphStyle('Th', parent=base, fontName='Helvetica-Bold', fontSize=7.5, leading=9,
                                 textColor=colors.HexColor('#334155')),
            'th_der': ParagraphStyle('ThDer', parent=base, fontName='Helvetica-Bold', fontSize=7.5, leading=9,
                                     textColor=colors.HexColor('#334155'), alignment=2),
            'kpi_label': ParagraphStyle('KpiLabel', parent=base, fontName='Helvetica-Bold', fontSize=7, leading=9,
                                        textColor=COLOR_SECUNDARIO),
            'kpi_valor': ParagraphStyle('KpiValor', parent=base, fontName='Helvetica-Bold', fontSize=20, leading=24,
                                        textColor=COLOR_TEXTO),
            'kpi_sub': ParagraphStyle('KpiSub', parent=base, fontSize=7, leading=9, textColor=COLOR_SECUNDARIO),
            'nota': ParagraphStyle('Nota', parent=base, fontSize=8.5, leading=11.5,
                                   textColor=colors.HexColor('#134E4A')),
            'anexo': ParagraphStyle('Anexo', parent=base, fontName='Helvetica-Bold', fontSize=15, leading=18,
                                    textColor=COLOR_TEXTO),
        }

    @staticmethod
    def _seccion(titulo: str, estilos: Dict[str, ParagraphStyle], derecha: str = '') -> Table:
        """Encabezado de bloque: título a la izquierda, dato destacado a la derecha, línea inferior."""
        t = Table(
            [[Paragraph(_esc(titulo), estilos['h3']), Paragraph(_esc(derecha), estilos['h3_der'])]],
            colWidths=[ANCHO_UTIL * 0.7, ANCHO_UTIL * 0.3],
        )
        t.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, -1), 0.6, COLOR_BORDE),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        return t

    @staticmethod
    def _tabla(datos: List[List[Any]], anchos: List[float], extra: List[Tuple] | None = None) -> Table:
        """Tabla limpia: cabecera gris claro, solo líneas horizontales finas."""
        t = Table(datos, colWidths=anchos, repeatRows=1)
        estilo = [
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_FONDO_SUAVE),
            ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.HexColor('#CBD5E1')),
            ('LINEBELOW', (0, 1), (-1, -1), 0.4, colors.HexColor('#EEF2F6')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        t.setStyle(TableStyle(estilo + (extra or [])))
        return t

    @classmethod
    def _kpis(cls, m: Dict[str, Any], est: Dict[str, ParagraphStyle]) -> Table:
        emitidos = m.get('total_emitidos', 0)
        sub_atendidos = (
            f"{_n(emitidos)} ingresos · {_n(m.get('total_cancelados', 0))} ausentes · "
            f"{_n(m.get('total_en_curso', 0))} en curso"
        )
        tarjetas = [
            ('ATENDIDOS', _n(m.get('total_atendidos', 0)), sub_atendidos, None),
            ('ESPERA PROMEDIO', f"{_dec(m.get('promedio_espera_minutos', 0))} min", 'Ingreso → llamado', None),
            ('ATENCIÓN PROMEDIO', f"{_dec(m.get('promedio_atencion_minutos', 0))} min", 'Duración en box', None),
            ('CRÍTICOS', _n(m.get('total_criticos_atendidos', 0)), 'Guardia + Médicos', COLOR_ROJO),
        ]
        gap, ancho_t = 8, (ANCHO_UTIL - 3 * 8) / 4
        fila, anchos = [], []
        for i, (lbl, val, sub, color) in enumerate(tarjetas):
            estilo_valor = est['kpi_valor']
            if color:
                estilo_valor = ParagraphStyle('KpiValorRojo', parent=est['kpi_valor'], textColor=color)
            fila.append([Paragraph(lbl, est['kpi_label']), Paragraph(val, estilo_valor), Paragraph(_esc(sub), est['kpi_sub'])])
            anchos.append(ancho_t)
            if i < 3:
                fila.append('')
                anchos.append(gap)
        t = Table([fila], colWidths=anchos)
        estilo = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 8),
                  ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 7),
                  ('BOTTOMPADDING', (0, 0), (-1, -1), 7)]
        for col in range(0, 7, 2):
            estilo.append(('BOX', (col, 0), (col, 0), 0.8, COLOR_BORDE))
        for col in (1, 3, 5):
            estilo.append(('LEFTPADDING', (col, 0), (col, 0), 0))
            estilo.append(('RIGHTPADDING', (col, 0), (col, 0), 0))
        t.setStyle(TableStyle(estilo))
        return t

    @staticmethod
    def _filas_triage(m: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
        conteo = {s['clasificacion_triage']: s.get('total_pacientes', 0) for s in m.get('sla_triage', [])}
        for d in m.get('distribucion_triage', []):
            conteo.setdefault(d['clasificacion_triage'], d.get('cantidad', 0))
        filas = [
            {'key': k, 'label': lbl, 'color': col, 'objetivo': obj, 'cantidad': int(conteo.get(k, 0) or 0)}
            for k, lbl, col, obj in TRIAGE_META
        ]
        return filas, sum(f['cantidad'] for f in filas)

    @staticmethod
    def _muestras(m: Dict[str, Any]) -> List[Dict[str, Any]]:
        conteo = {k: 0 for k, _, _ in MUESTRAS_ESTILO}
        for ins in m.get('insumos_tubos', []):
            tipo = str(ins.get('tipo_muestra') or '').strip().lower()
            if tipo in MUESTRAS_SANGRE:
                grupo = 'sangre'
            elif tipo in ('orina', 'materia fecal'):
                grupo = tipo
            else:
                grupo = 'otros'
            conteo[grupo] += int(ins.get('total_tubos', 0) or 0)
        items = [{'label': lbl, 'valor': conteo[k], 'color': col} for k, lbl, col in MUESTRAS_ESTILO]
        return [i for i in items if i['valor'] > 0 or i['label'] != 'Otros']

    @classmethod
    def _nota_lectura(cls, m: Dict[str, Any], filas: List[Dict[str, Any]], total_triage: int) -> str:
        partes = []
        if total_triage > 0:
            dom = max(filas, key=lambda f: f['cantidad'])
            partes.append(f"El {_pct(dom['cantidad'], total_triage)} de los pacientes fue «{dom['label'].lower()}».")
        espera = float(m.get('promedio_espera_minutos', 0) or 0)
        if espera > 0:
            estado = 'superó' if espera > OBJETIVO_ESPERA_GENERAL_MIN else 'cumplió'
            partes.append(
                f"La espera promedio ({_dec(espera)} min) {estado} el objetivo de {OBJETIVO_ESPERA_GENERAL_MIN} min."
            )
        return ' '.join(partes) or 'Sin actividad registrada en la jornada.'

    @classmethod
    def generar(cls, metricas: Dict[str, Any]) -> bytes:
        """
        Compila el informe oficial en formato PDF en memoria a partir de un diccionario de métricas.
        """
        est = cls._estilos()
        fecha_txt = _fecha_local(metricas.get('fecha', ''))
        generado = timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')

        def encabezado(c: canvas.Canvas, _doc) -> None:
            c.saveState()
            top = ALTO_PAGINA - 30
            c.setFillColor(COLOR_TEAL)
            c.roundRect(MARGEN, top - 26, 30, 26, 6, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont('Helvetica-Bold', 8)
            c.drawCentredString(MARGEN + 15, top - 16, LOGO_TEXTO)
            c.setFillColor(COLOR_TEXTO)
            c.setFont('Helvetica-Bold', 11)
            c.drawString(MARGEN + 40, top - 11, INSTITUCION)
            c.setFillColor(COLOR_SECUNDARIO)
            c.setFont('Helvetica', 8)
            c.drawString(MARGEN + 40, top - 23, TITULO_INFORME)
            c.setFillColor(COLOR_TEXTO)
            c.setFont('Helvetica-Bold', 10)
            c.drawRightString(ANCHO_PAGINA - MARGEN, top - 11, f"Jornada {fecha_txt}")
            c.setFillColor(COLOR_SECUNDARIO)
            c.setFont('Helvetica', 7.5)
            c.drawRightString(ANCHO_PAGINA - MARGEN, top - 23, f"Generado: {generado} (hora Argentina)")
            c.setStrokeColor(COLOR_TEAL)
            c.setLineWidth(1.6)
            c.line(MARGEN, top - 34, ANCHO_PAGINA - MARGEN, top - 34)
            c.restoreState()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            rightMargin=MARGEN - 6, leftMargin=MARGEN - 6, topMargin=84, bottomMargin=44,  # -6: padding interno del frame
            title=f"{TITULO_INFORME} {fecha_txt}", author=INSTITUCION,
        )
        el: List[Any] = []

        # ======================================================================
        # PÁGINA 1: RESUMEN DE LA JORNADA
        # ======================================================================
        el.append(Paragraph("Resumen de la jornada", est['titulo']))
        el.append(Paragraph("Atención de pacientes y estudios realizados", est['subtitulo']))
        el.append(Spacer(1, 10))
        el.append(cls._kpis(metricas, est))
        el.append(Spacer(1, 14))

        filas_triage, total_triage = cls._filas_triage(metricas)
        el.append(cls._seccion(
            "Distribución por triage", est,
            f"{_n(total_triage)} {'paciente' if total_triage == 1 else 'pacientes'}",
        ))
        el.append(Spacer(1, 6))
        el.append(_grafico_triage(filas_triage, total_triage))
        el.append(Spacer(1, 14))

        # Estudios por sección (top 5 + Otras) y por muestra, lado a lado
        secciones = sorted(
            metricas.get('resumen_secciones', []), key=lambda s: s.get('total_estudios', 0), reverse=True
        )
        total_estudios = int(metricas.get('total_estudios', 0) or 0)
        top = [(s['nombre_seccion'], int(s['total_estudios'])) for s in secciones[:5]]
        resto = secciones[5:]
        if resto:
            top.append((f"Otras ({len(resto)} secciones)", sum(int(s['total_estudios']) for s in resto)))

        ancho_izq, ancho_der, gap = 290.0, 213.0, 20.0
        if top and total_estudios > 0:
            graf_secciones: Any = _grafico_lollipop(top, ancho_izq)
        else:
            graf_secciones = Paragraph("Sin estudios registrados en la jornada.", est['celda'])
        muestras = cls._muestras(metricas)
        if total_estudios > 0 and muestras:
            graf_muestras: Any = _grafico_columnas(muestras, ancho_der)
        else:
            graf_muestras = Paragraph("Sin estudios registrados en la jornada.", est['celda'])

        def _bloque(titulo: str, ancho: float, grafico: Any) -> List[Any]:
            cab = Table(
                [[Paragraph(titulo, est['h3']), Paragraph(_n(total_estudios), est['h3_der'])]],
                colWidths=[ancho * 0.72, ancho * 0.28],
            )
            cab.setStyle(TableStyle([
                ('LINEBELOW', (0, 0), (-1, -1), 0.6, COLOR_BORDE), ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            return [cab, Spacer(1, 6), grafico]

        dos_cols = Table(
            [[_bloque("Estudios por sección", ancho_izq, graf_secciones), '',
              _bloque("Estudios por muestra", ancho_der, graf_muestras)]],
            colWidths=[ancho_izq, gap, ancho_der],
        )
        dos_cols.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        el.append(dos_cols)
        el.append(Spacer(1, 14))

        nota = Table([[Paragraph(_esc(cls._nota_lectura(metricas, filas_triage, total_triage)), est['nota'])]],
                     colWidths=[ANCHO_UTIL])
        nota.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0FDFA')),
            ('LINEBEFORE', (0, 0), (0, -1), 2.5, COLOR_TEAL),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        el.append(nota)

        # ======================================================================
        # PÁGINA 2: TIEMPOS, FRANJAS Y AUDITORÍA
        # ======================================================================
        el.append(PageBreak())
        el.append(cls._seccion("Cumplimiento de tiempos por triage", est))
        el.append(Spacer(1, 6))

        sla_por_key = {s['clasificacion_triage']: s for s in metricas.get('sla_triage', [])}
        datos = [[
            Paragraph("Categoría", est['th']), Paragraph("Pacientes", est['th_der']),
            Paragraph("Espera prom.", est['th_der']), Paragraph("Objetivo", est['th_der']),
            Paragraph("Estado", est['th']),
        ]]
        extra_sla: List[Tuple] = []
        for k, lbl, _col, objetivo in TRIAGE_META:
            sla = sla_por_key.get(k)
            if objetivo is None or not sla or not sla.get('total_pacientes'):
                continue
            espera = float(sla.get('promedio_espera_minutos', 0) or 0)
            if espera <= 0:
                estado = Paragraph("<font color='#64748B'>Sin datos</font>", est['celda'])
            elif espera > objetivo:
                estado = Paragraph("<font color='#B91C1C'><b>Excedido</b></font>", est['celda'])
            else:
                estado = Paragraph("<font color='#0F766E'><b>Cumple</b></font>", est['celda'])
            datos.append([
                Paragraph(_esc(lbl), est['celda']), Paragraph(_n(sla['total_pacientes']), est['celda_der']),
                Paragraph(f"{_dec(espera)} min", est['celda_der']), Paragraph(f"{_dec(objetivo, 0)} min", est['celda_der']),
                estado,
            ])
        if len(datos) == 1:
            datos.append([Paragraph("Sin datos de espera en la jornada", est['celda']), '', '', '', ''])
        el.append(cls._tabla(datos, [190, 70, 85, 80, 98], extra_sla))
        el.append(Spacer(1, 16))

        franjas = metricas.get('franjas_horarias', [])
        el.append(cls._seccion("Pacientes por franja horaria", est))
        el.append(Spacer(1, 6))
        if franjas:
            d = Drawing(ANCHO_UTIL, 100)
            base_y, alto_max = 30, 56
            maximo = max([int(f.get('total_emitidos', 0)) for f in franjas] + [1])
            slot = ANCHO_UTIL / len(franjas)
            for i, f in enumerate(franjas):
                cx = slot * i + slot / 2
                valor = int(f.get('total_emitidos', 0) or 0)
                h = max(2, alto_max * valor / maximo) if valor else 1
                d.add(Rect(cx - 30, base_y, 60, h, fillColor=COLOR_TEAL, strokeColor=None))
                d.add(String(cx, base_y + h + 4, _n(valor), fontName='Helvetica-Bold', fontSize=9,
                             fillColor=COLOR_TEXTO, textAnchor='middle'))
                d.add(String(cx, base_y - 11, _truncar(f['nombre'], 'Helvetica-Bold', 7.5, slot - 8),
                             fontName='Helvetica-Bold', fontSize=7.5, fillColor=COLOR_TEXTO, textAnchor='middle'))
                d.add(String(cx, base_y - 21, str(f['rango_display']).replace(':00:00', ':00').replace(':59:59', ':59'),
                             fontName='Helvetica', fontSize=7, fillColor=COLOR_SECUNDARIO, textAnchor='middle'))
            d.add(Line(0, base_y, ANCHO_UTIL, base_y, strokeColor=colors.HexColor('#CBD5E1'), strokeWidth=0.6))
            el.append(d)
            el.append(Spacer(1, 8))

            datos = [[
                Paragraph("Franja", est['th']), Paragraph("Emitidos", est['th_der']),
                Paragraph("Atendidos", est['th_der']), Paragraph("Cancelados", est['th_der']),
                Paragraph("Espera prom.", est['th_der']), Paragraph("Atención prom.", est['th_der']),
            ]]
            for f in franjas:
                datos.append([
                    Paragraph(_esc(f['nombre']), est['celda']), Paragraph(_n(f['total_emitidos']), est['celda_der']),
                    Paragraph(_n(f['total_atendidos']), est['celda_der']), Paragraph(_n(f['total_cancelados']), est['celda_der']),
                    Paragraph(f"{_dec(f['promedio_espera_minutos'])} min", est['celda_der']),
                    Paragraph(f"{_dec(f['promedio_atencion_minutos'])} min", est['celda_der']),
                ])
            el.append(cls._tabla(datos, [158, 55, 60, 65, 90, 95]))
        el.append(Spacer(1, 16))

        auditoria = metricas.get('auditoria_box', {}) or {}
        el.append(cls._seccion("Auditoría de modificaciones en box", est))
        el.append(Spacer(1, 6))
        datos = [
            [Paragraph("Cargados en admisión", est['th_der']), Paragraph("Agregados en box", est['th_der']),
             Paragraph("Cancelados en box", est['th_der']), Paragraph("Tasa de rectificación", est['th_der'])],
            [Paragraph(_n(auditoria.get('total_cargados_admision', 0)), est['celda_der']),
             Paragraph(f"<font color='#0F766E'><b>+{_n(auditoria.get('total_agregados_box', 0))}</b></font>", est['celda_der']),
             Paragraph(f"<font color='#B91C1C'><b>-{_n(auditoria.get('total_cancelados_box', 0))}</b></font>", est['celda_der']),
             Paragraph(f"<b>{_dec(auditoria.get('tasa_rectificacion_porcentaje', 0))}%</b>", est['celda_der'])],
        ]
        el.append(cls._tabla(datos, [130, 131, 131, 131]))
        el.append(Spacer(1, 14))

        nota_anexo = Table([[Paragraph(
            "Las páginas siguientes (anexo) incluyen el resumen por sección, insumos, el detalle de prácticas "
            "y el rendimiento del personal.", est['nota'])]], colWidths=[ANCHO_UTIL])
        nota_anexo.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F0FDFA')),
            ('LINEBEFORE', (0, 0), (0, -1), 2.5, COLOR_TEAL),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        el.append(nota_anexo)

        # ======================================================================
        # ANEXO
        # ======================================================================
        el.append(PageBreak())
        el.append(Paragraph("Anexo", est['anexo']))
        el.append(Paragraph("Detalle de la jornada", est['subtitulo']))
        el.append(Spacer(1, 10))

        # Resumen por sección
        el.append(cls._seccion("Resumen por sección de laboratorio", est, f"{_n(total_estudios)} estudios"))
        el.append(Spacer(1, 6))
        datos = [[Paragraph("Sección", est['th']), Paragraph("Estudios", est['th_der']),
                  Paragraph("% del total", est['th_der'])]]
        for s in secciones:
            datos.append([
                Paragraph(_esc(s['nombre_seccion']), est['celda']), Paragraph(_n(s['total_estudios']), est['celda_der']),
                Paragraph(f"{_dec(s.get('porcentaje', 0))}%", est['celda_der']),
            ])
        if len(datos) == 1:
            datos.append([Paragraph("Sin estudios registrados en la jornada", est['celda']), '', ''])
        el.append(cls._tabla(datos, [323, 100, 100]))
        el.append(Spacer(1, 16))

        # Insumos
        el.append(cls._seccion("Logística de muestras e insumos", est))
        el.append(Spacer(1, 6))
        datos = [[Paragraph("Tipo de muestra / insumo", est['th']), Paragraph("Unidades", est['th_der']),
                  Paragraph("Proporción", est['th_der'])]]
        for ins in metricas.get('insumos_tubos', []):
            datos.append([
                Paragraph(_esc(ins['descripcion_tubo']), est['celda']), Paragraph(_n(ins['total_tubos']), est['celda_der']),
                Paragraph(f"{_dec(ins.get('porcentaje', 0))}%", est['celda_der']),
            ])
        if len(datos) == 1:
            datos.append([Paragraph("Sin insumos requeridos", est['celda']), '', ''])
        el.append(cls._tabla(datos, [323, 100, 100]))
        el.append(Spacer(1, 16))

        # Detalle de prácticas
        el.append(cls._seccion("Detalle de prácticas por sección", est))
        el.append(Spacer(1, 6))
        hay_practicas = False
        for sec in secciones:
            practicas = sec.get('practicas', [])
            if not practicas:
                continue
            hay_practicas = True
            datos = [[Paragraph("Cód.", est['th']), Paragraph("Práctica", est['th']),
                      Paragraph("Muestra", est['th']), Paragraph("Cantidad", est['th_der'])]]
            for pr in practicas:
                datos.append([
                    Paragraph(_esc(pr.get('codigo') or '—'), est['celda']), Paragraph(_esc(pr['nombre']), est['celda']),
                    Paragraph(_esc(str(pr.get('tipo_muestra', '')).capitalize()), est['celda']),
                    Paragraph(f"<b>{_n(pr['total'])}</b>", est['celda_der']),
                ])
            titulo_sec = Paragraph(
                f"<font color='#0F766E'><b>{_esc(sec['nombre_seccion'])}</b></font> "
                f"<font color='#64748B'>· {_n(sec['total_estudios'])} estudios</font>", est['celda_sec'])
            el.append(Spacer(1, 4))
            el.append(titulo_sec)
            el.append(Spacer(1, 3))
            el.append(cls._tabla(datos, [60, 258, 110, 95]))
            el.append(Spacer(1, 6))
        if not hay_practicas:
            el.append(Paragraph("<i>No se realizaron prácticas en la jornada seleccionada.</i>", est['celda']))

        # Personal
        el.append(PageBreak())
        el.append(cls._seccion("Rendimiento del personal asistencial", est))
        el.append(Spacer(1, 8))

        el.append(Paragraph("<b>Operadores de admisión</b> (por pacientes recepcionados)", est['celda']))
        el.append(Spacer(1, 4))
        datos = [[Paragraph("Operador", est['th']), Paragraph("Matrícula / DNI", est['th']),
                  Paragraph("Correo", est['th']), Paragraph("Tickets", est['th_der'])]]
        for adm in metricas.get('rendimiento_admision', []):
            mat = adm.get('personal_admision__matricula') or f"DNI {adm.get('personal_admision__dni', '—')}"
            datos.append([
                Paragraph(f"<b>{_esc(adm['nombre_completo'])}</b>", est['celda']), Paragraph(_esc(mat), est['celda']),
                Paragraph(_esc(adm.get('personal_admision__email', '—')), est['celda']),
                Paragraph(f"<b>{_n(adm['pacientes_recepcionados'])}</b>", est['celda_der']),
            ])
        if len(datos) == 1:
            datos.append([Paragraph("Sin emisiones registradas", est['celda']), '', '', ''])
        el.append(cls._tabla(datos, [173, 100, 170, 80]))
        el.append(Spacer(1, 16))

        el.append(Paragraph("<b>Técnicos de box de extracción</b> (por pacientes atendidos)", est['celda']))
        el.append(Spacer(1, 4))
        datos = [[Paragraph("Técnico", est['th']), Paragraph("Matrícula", est['th']), Paragraph("Correo", est['th']),
                  Paragraph("Atendidos", est['th_der']), Paragraph("Ausentes", est['th_der']),
                  Paragraph("Atención prom.", est['th_der'])]]
        for bx in metricas.get('rendimiento_box', []):
            datos.append([
                Paragraph(f"<b>{_esc(bx['nombre_completo'])}</b>", est['celda']), Paragraph(_esc(bx.get('matricula', '-')), est['celda']),
                Paragraph(_esc(bx.get('email', '')), est['celda']),
                Paragraph(f"<b>{_n(bx['pacientes_atendidos'])}</b>", est['celda_der']),
                Paragraph(_n(bx.get('pacientes_ausentes', 0)), est['celda_der']),
                Paragraph(f"{_dec(bx['promedio_atencion_minutos'])} min", est['celda_der']),
            ])
        if len(datos) == 1:
            datos.append([Paragraph("Sin atenciones registradas en box", est['celda']), '', '', '', '', ''])
        el.append(cls._tabla(datos, [125, 60, 133, 55, 55, 95]))

        doc.build(el, onFirstPage=encabezado, onLaterPages=encabezado, canvasmaker=NumberedCanvas)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes


__all__ = ['ReportPdfGenerator', 'NumberedCanvas']
