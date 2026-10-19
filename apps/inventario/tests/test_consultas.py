from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventario.consultas import (
    DIAS_POR_VENCER,
    kg_en_bodega,
    lotes_con_existencia,
    lotes_por_vencer,
)
from apps.inventario.models import Existencia, Lote


@pytest.fixture
def hoy():
    return timezone.localdate()


def _lote(datos_lote, codigo, vence):
    return Lote.objects.create(
        codigo=codigo, origen="INVENTARIO_INICIAL", **{**datos_lote, "fecha_vencimiento": vence}
    )


def test_sin_existencias_todo_en_cero(db):
    assert kg_en_bodega() == Decimal("0")
    assert lotes_con_existencia().count() == 0
    assert lotes_por_vencer() == []


def test_suma_las_ubicaciones_de_un_lote(lote, bodega, tunel):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("30"))
    Existencia.objects.create(lote=lote, ubicacion=tunel, cantidad=Decimal("12.50"))
    assert kg_en_bodega() == Decimal("42.50")
    (con_stock,) = lotes_con_existencia()
    assert con_stock.kg == Decimal("42.50")


def test_ignora_existencia_en_cero(lote, bodega, tunel):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("10"))
    Existencia.objects.create(lote=lote, ubicacion=tunel, cantidad=Decimal("0"))
    assert kg_en_bodega() == Decimal("10")
    assert lotes_con_existencia().get().kg == Decimal("10")


def test_por_vencer_incluye_el_limite_y_los_vencidos(datos_lote, bodega, hoy):
    en_limite = _lote(datos_lote, "L-A", hoy + timedelta(days=DIAS_POR_VENCER))
    vencido = _lote(datos_lote, "L-B", hoy - timedelta(days=2))
    lejano = _lote(datos_lote, "L-C", hoy + timedelta(days=DIAS_POR_VENCER + 1))
    for lote in (en_limite, vencido, lejano):
        Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("5"))

    resultado = lotes_por_vencer()

    assert [lote.codigo for lote in resultado] == ["L-B", "L-A"]
    assert [lote.dias_restantes for lote in resultado] == [-2, DIAS_POR_VENCER]


def test_por_vencer_ignora_lotes_sin_existencia(datos_lote, bodega, hoy):
    agotado = _lote(datos_lote, "L-A", hoy + timedelta(days=1))
    Existencia.objects.create(lote=agotado, ubicacion=bodega, cantidad=Decimal("0"))
    assert lotes_por_vencer() == []
