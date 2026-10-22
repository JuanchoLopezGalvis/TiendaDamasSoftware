"""Generación de los reportes en PDF (con reportlab)."""
from html import escape
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

__all__ = ['cm', 'Spacer', 'tabla', 'grafico_barras', 'parrafo', 'celda', 'reporte']

AZUL = colors.HexColor('#3b4a8c')
GRIS = colors.HexColor('#6b6b72')
FONDO = colors.HexColor('#f1f1f4')
LINEA = colors.HexColor('#d9d9de')


def _estilos():
    e = getSampleStyleSheet()
    e['Title'].textColor = AZUL
    e['Title'].alignment = 0          # izquierda
    e['Normal'].fontSize = 10
    e['Heading2'].textColor = AZUL
    e['Heading2'].fontSize = 13
    return e


def tabla(encabezados, filas, derecha=(), total=None, anchos=None):
    """Tabla con encabezado azul y filas alternas. `derecha`: índices de columnas numéricas."""
    # Los Paragraph se dejan tal cual para que el texto largo haga salto de línea
    datos = [encabezados] + [[c if isinstance(c, Paragraph) else str(c) for c in f] for f in filas]
    if total:
        datos.append([str(c) for c in total])
    t = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), AZUL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, LINEA),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, FONDO]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]
    for c in derecha:
        estilo.append(('ALIGN', (c, 0), (c, -1), 'RIGHT'))
    if total:
        estilo += [
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('LINEABOVE', (0, -1), (-1, -1), 1, AZUL),
        ]
    t.setStyle(TableStyle(estilo))
    return t


def grafico_barras(etiquetas, valores, ancho=17 * cm, alto=6 * cm):
    d = Drawing(ancho, alto)
    g = VerticalBarChart()
    g.x, g.y = 45, 25
    g.width, g.height = min(ancho - 60, 40 + 35 * len(valores)), alto - 40
    g.data = [valores]
    g.bars[0].fillColor = AZUL
    g.bars[0].strokeColor = None
    g.valueAxis.valueMin = 0
    g.valueAxis.labels.fontSize = 7
    g.valueAxis.labelTextFormat = lambda v: f'${v / 1000:,.0f}k'.replace(',', '.')
    g.categoryAxis.categoryNames = etiquetas
    g.categoryAxis.labels.fontSize = 6
    g.categoryAxis.labels.angle = 45 if len(etiquetas) > 12 else 0
    g.categoryAxis.labels.boxAnchor = 'ne' if len(etiquetas) > 12 else 'n'
    d.add(g)
    return d


def reporte(titulo, filtros, contenido, usuario, nombre_archivo):
    """Arma el PDF y lo devuelve como descarga.

    filtros: lista de (etiqueta, valor) que se muestran bajo el título.
    contenido: lista de elementos de reportlab (tablas, gráficos, párrafos).
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, title=titulo, author='TiendaDamas',
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
    )
    e = _estilos()
    ahora = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    generado_por = getattr(getattr(usuario, 'empleado', None), 'nombre_completo', None) or usuario.get_username()

    partes = [
        Paragraph('TiendaDamas', e['Normal']),
        Paragraph(titulo, e['Title']),
        Paragraph(' · '.join(f'<b>{k}:</b> {v}' for k, v in filtros), e['Normal']),
        Paragraph(f'<font color="#6b6b72">Generado el {ahora} por {generado_por}</font>', e['Normal']),
        Spacer(1, 0.6 * cm),
    ] + contenido

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(GRIS)
        canvas.drawRightString(letter[0] - 2 * cm, 1.2 * cm, f'Página {doc.page}')
        canvas.restoreState()

    doc.build(partes, onFirstPage=pie, onLaterPages=pie)

    resp = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return resp


def parrafo(texto, estilo='Normal'):
    return Paragraph(texto, _estilos()[estilo])


def celda(texto):
    """Texto de una celda que puede ser largo: hace salto de línea dentro de la tabla."""
    e = _estilos()['Normal'].clone('celda', fontSize=8, leading=10)
    return Paragraph(escape(str(texto)), e)
