"""Estructura común, formato colombiano y exportación a CSV y PDF (RF-66, RN-40)."""

from datetime import date
from decimal import Decimal

from apps.reportes.exportar import respuesta_csv, respuesta_pdf
from apps.reportes.reporte import Columna, Reporte, formatear, numero


def _reporte(filas=None):
    return Reporte(
        titulo="Prueba de reporte",
        archivo="prueba",
        columnas=[
            Columna("producto", "Producto"),
            Columna("vence", "Vence", "fecha"),
            Columna("kg", "Kg", "kg"),
        ],
        filas=filas
        if filas is not None
        else [{"producto": "Pechuga & muslo", "vence": date(2026, 12, 1), "kg": Decimal("1234.5")}],
        filtros=[("Producto", "Todos")],
        resumen=[("Existencia total", Decimal("1234.5"), "kg")],
        totales={"producto": "Total", "kg": Decimal("1234.5")},
    )


def test_numero_en_formato_colombiano():
    assert numero(Decimal("1234567.891")) == "1.234.567,89"
    assert numero(Decimal("-2")) == "-2,00"
    assert numero(Decimal("1234.5"), miles=False) == "1234,50"


def test_formatear_por_tipo():
    assert formatear(Decimal("12.345"), "porcentaje") == "12,3 %"
    assert formatear(12000, "entero") == "12.000"
    assert formatear(date(2026, 1, 5), "fecha") == "05/01/2026"
    assert formatear(None, "kg") == ""


def test_celdas_y_fila_de_totales():
    reporte = _reporte()
    assert reporte.celdas(reporte.filas[0]) == ["Pechuga & muslo", "01/12/2026", "1.234,50"]
    assert reporte.fila_de_totales() == ["Total", "", "1.234,50"]
    assert Reporte(titulo="x", columnas=[]).fila_de_totales() is None


def test_csv_para_excel_en_espanol():
    """RF-66: separador «;», coma decimal sin miles y marca UTF-8 para las tildes."""
    respuesta = respuesta_csv(_reporte())
    assert respuesta["Content-Type"].startswith("text/csv")
    assert 'filename="invendata-prueba-' in respuesta["Content-Disposition"]
    texto = respuesta.content.decode("utf-8")
    assert texto.startswith("﻿Prueba de reporte")
    assert "Producto;Todos" in texto
    assert "Producto;Vence;Kg" in texto
    assert "Pechuga & muslo;01/12/2026;1234,50" in texto
    assert "Total;;1234,50" in texto


def test_pdf_se_genera(gerente):
    respuesta = respuesta_pdf(_reporte(), gerente)
    assert respuesta["Content-Type"] == "application/pdf"
    assert respuesta.content.startswith(b"%PDF")
    assert 'filename="invendata-prueba-' in respuesta["Content-Disposition"]


def test_pdf_sin_filas_y_con_muchas_paginas():
    """Un reporte vacío o largo también sale: el encabezado se repite en cada página."""
    assert respuesta_pdf(_reporte(filas=[])).content.startswith(b"%PDF")
    largas = [
        {"producto": f"Producto <{i}>", "vence": date(2026, 12, 1), "kg": Decimal(i)}
        for i in range(300)
    ]
    assert respuesta_pdf(_reporte(filas=largas)).content.startswith(b"%PDF")
