"""Exportación de cualquier reporte a CSV y a PDF (RF-66, RN-40).

CSV: separador «;», coma decimal y marca UTF-8, para que Excel en español lo abra con doble
clic con tildes y números correctos. PDF: tamaño carta, horizontal si hay muchas columnas,
con el encabezado de filtros, las cifras clave, la tabla (el encabezado se repite en cada
página) y un pie con la fecha de generación, quién lo generó y el número de página.
"""

import csv
import io

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.reportes.reporte import formatear

AZUL = colors.HexColor("#13213a")
GRIS_CLARO = colors.HexColor("#f2f4f8")
GRIS_BORDE = colors.HexColor("#d5dae3")
POR_FILA = 4  # cifras clave por fila en el PDF


def _nombre(reporte, extension):
    fecha = timezone.localtime(reporte.generado).strftime("%Y%m%d-%H%M")
    return f"invendata-{reporte.archivo}-{fecha}.{extension}"


def _crudas(columnas, fila):
    """Celdas para el CSV: sin separador de miles, para que Excel las lea como números."""
    return [formatear(fila.get(c.clave), c.tipo, miles=False) for c in columnas]


def respuesta_csv(reporte):
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow([reporte.titulo])
    for etiqueta, valor in reporte.filtros:
        escritor.writerow([etiqueta, valor])
    generado = timezone.localtime(reporte.generado).strftime("%d/%m/%Y %H:%M")
    escritor.writerow(["Generado", generado])
    for tabla in reporte.tablas:
        escritor.writerow([])
        if tabla.titulo:
            escritor.writerow([tabla.titulo])
        escritor.writerow([c.titulo for c in tabla.columnas])
        for fila in tabla.filas:
            escritor.writerow(_crudas(tabla.columnas, fila))
        if tabla.totales:
            escritor.writerow(_crudas(tabla.columnas, tabla.totales))
    # La marca UTF-8 al inicio hace que Excel reconozca las tildes.
    respuesta = HttpResponse("\ufeff" + salida.getvalue(), content_type="text/csv; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre(reporte, "csv")}"'
    return respuesta


def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=base["Title"], fontSize=15, textColor=AZUL, alignment=0, spaceAfter=4
        ),
        "filtro": ParagraphStyle("filtro", parent=base["Normal"], fontSize=8.5, leading=11),
        "celda": ParagraphStyle("celda", parent=base["Normal"], fontSize=7.5, leading=9),
        "cabeza": ParagraphStyle(
            "cabeza", parent=base["Normal"], fontSize=7.5, leading=9, textColor=colors.white
        ),
        "cifra": ParagraphStyle(
            "cifra", parent=base["Normal"], fontSize=11, leading=14, textColor=AZUL
        ),
        "seccion": ParagraphStyle(
            "seccion", parent=base["Heading2"], fontSize=11, textColor=AZUL, spaceBefore=4
        ),
        "nota": ParagraphStyle(
            "nota", parent=base["Normal"], fontSize=7.5, leading=10, textColor=colors.grey
        ),
    }


def _texto(valor):
    """Escapa los caracteres que el marcado de reportlab interpreta."""
    return str(valor).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _anchos(columnas, ancho):
    """Reparte el ancho útil: el texto pesa el doble que una cifra."""
    pesos = [1 if c.numerica else 2 for c in columnas]
    return [ancho * p / sum(pesos) for p in pesos]


def _tabla_pdf(tabla, estilos, ancho):
    """Una tabla del reporte: encabezado que se repite, filas alternadas y totales."""
    datos = [[Paragraph(f"<b>{_texto(c.titulo)}</b>", estilos["cabeza"]) for c in tabla.columnas]]
    for fila in tabla.filas:
        datos.append([Paragraph(_texto(v), estilos["celda"]) for v in tabla.celdas(fila)])
    totales = tabla.fila_de_totales()
    if totales:
        datos.append([Paragraph(f"<b>{_texto(v)}</b>", estilos["celda"]) for v in totales])
    if not tabla.filas:
        datos.append([Paragraph("Sin datos para los filtros elegidos.", estilos["celda"])])

    resultado = Table(datos, colWidths=_anchos(tabla.columnas, ancho), repeatRows=1, hAlign="LEFT")
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLARO]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, GRIS_BORDE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for indice, columna in enumerate(tabla.columnas):
        if columna.numerica:
            estilo.append(("ALIGN", (indice, 0), (indice, -1), "RIGHT"))
    if totales:
        estilo.append(("LINEABOVE", (0, -1), (-1, -1), 1, AZUL))
    if not tabla.filas:
        estilo.append(("SPAN", (0, 1), (-1, 1)))
    resultado.setStyle(TableStyle(estilo))
    return resultado


def respuesta_pdf(reporte, usuario=None):
    buffer = io.BytesIO()
    horizontal = max((len(t.columnas) for t in reporte.tablas), default=0) > 6
    tamano = landscape(letter) if horizontal else letter
    estilos = _estilos()
    quien = getattr(usuario, "nombre_completo", "") if usuario else ""
    generado = timezone.localtime(reporte.generado).strftime("%d/%m/%Y %H:%M")
    ancho = tamano[0] - 3 * cm  # menos las márgenes izquierda y derecha

    def pie(lienzo, documento):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 7)
        lienzo.setFillColor(colors.grey)
        texto = f"InvenData · Pid Consulting S.A.S. · Generado el {generado}"
        if quien:
            texto += f" por {quien}"
        lienzo.drawString(documento.leftMargin, 1.1 * cm, texto)
        lienzo.drawRightString(
            tamano[0] - documento.rightMargin, 1.1 * cm, f"Página {documento.page}"
        )
        lienzo.restoreState()

    documento = SimpleDocTemplate(
        buffer,
        pagesize=tamano,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.8 * cm,
        title=reporte.titulo,
        author="InvenData",
    )
    elementos = [Paragraph(_texto(reporte.titulo), estilos["titulo"])]
    for etiqueta, valor in reporte.filtros:
        elementos.append(
            Paragraph(f"<b>{_texto(etiqueta)}:</b> {_texto(valor)}", estilos["filtro"])
        )
    elementos.append(Spacer(1, 0.3 * cm))

    if reporte.resumen:
        # Las cifras clave en una rejilla de cuatro por fila: etiqueta arriba, valor abajo.
        celdas = []
        for inicio in range(0, len(reporte.resumen), POR_FILA):
            grupo = reporte.resumen[inicio : inicio + POR_FILA]
            vacias = [""] * (POR_FILA - len(grupo))
            celdas.append(
                [Paragraph(f"<b>{_texto(e)}</b>", estilos["filtro"]) for e, _, _ in grupo] + vacias
            )
            celdas.append(
                [Paragraph(_texto(formatear(v, t)), estilos["cifra"]) for _, v, t in grupo] + vacias
            )
        cifras = Table(celdas, colWidths=[ancho / POR_FILA] * POR_FILA, hAlign="LEFT")
        cifras.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), GRIS_CLARO),
                    ("BOX", (0, 0), (-1, -1), 0.5, GRIS_BORDE),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        elementos += [cifras, Spacer(1, 0.4 * cm)]

    for tabla in reporte.tablas:
        if tabla.titulo:
            elementos.append(Paragraph(_texto(tabla.titulo), estilos["seccion"]))
        elementos.append(_tabla_pdf(tabla, estilos, ancho))
        if tabla.nota:
            elementos.append(Paragraph(_texto(tabla.nota), estilos["nota"]))
        elementos.append(Spacer(1, 0.4 * cm))
    if reporte.nota:
        elementos += [Spacer(1, 0.3 * cm), Paragraph(_texto(reporte.nota), estilos["nota"])]

    documento.build(elementos, onFirstPage=pie, onLaterPages=pie)
    respuesta = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{_nombre(reporte, "pdf")}"'
    return respuesta
