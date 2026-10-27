"""Restricciones de documento_embultaje, embultaje_registro y bulto (RN-26)."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.embultaje.models import Bulto, DocumentoEmbultaje, EmbultajeRegistro


def test_las_tablas_siguen_el_diccionario_de_datos():
    assert DocumentoEmbultaje._meta.db_table == "documento_embultaje"
    assert EmbultajeRegistro._meta.db_table == "embultaje_registro"
    assert Bulto._meta.db_table == "bulto"


def test_hay_un_solo_documento_por_dia(jefe_bodega):
    DocumentoEmbultaje.objects.create(fecha=date(2026, 10, 1), usuario=jefe_bodega)
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoEmbultaje.objects.create(fecha=date(2026, 10, 1), usuario=jefe_bodega)


@pytest.mark.parametrize(
    "cambios",
    [
        {"total_kilos": Decimal("0")},
        {"total_kilos": Decimal("70")},  # por bultos: debe ser 3 × 25
        {"usa_calculo_bultos": False},  # digitado con cantidad y peso por bulto
        {"cantidad_bultos": None},
        {"peso_por_bulto": Decimal("0"), "total_kilos": Decimal("0")},
    ],
)
def test_la_base_rechaza_registros_incoherentes(embultar, cambios):
    registro = embultar(usa_calculo_bultos=True, cantidad_bultos=3, peso_por_bulto="25")
    with pytest.raises(IntegrityError), transaction.atomic():
        EmbultajeRegistro.objects.filter(pk=registro.pk).update(**cambios)


def test_el_origen_y_el_destino_no_pueden_ser_el_mismo(embultar, bodega):
    registro = embultar(total_kilos="10")
    with pytest.raises(IntegrityError), transaction.atomic():
        EmbultajeRegistro.objects.filter(pk=registro.pk).update(ubicacion_destino=bodega)


def test_un_bulto_tiene_peso_positivo(embultar):
    registro = embultar(usa_calculo_bultos=True, cantidad_bultos=1, peso_por_bulto="25")
    with pytest.raises(IntegrityError), transaction.atomic():
        registro.bultos.update(peso=Decimal("0"))
