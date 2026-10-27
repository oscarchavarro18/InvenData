"""Inventario de punto de venta por producto (RF-48, RN-30, RNF-02, RNF-03)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.puntoventa.models import ExistenciaPuntoVenta, MovimientoPuntoVenta
from apps.puntoventa.servicios import (
    ExistenciaPdvInsuficiente,
    MovimientoPdvInvalido,
    existencia_pdv,
    registrar_movimiento_pdv,
)


def _mover(punto_venta, producto, usuario, tipo, cantidad):
    return registrar_movimiento_pdv(
        ubicacion=punto_venta, producto=producto, tipo=tipo, cantidad=cantidad, usuario=usuario
    )


def test_las_tablas_siguen_el_diccionario_de_datos():
    assert MovimientoPuntoVenta._meta.db_table == "movimiento_punto_venta"
    assert ExistenciaPuntoVenta._meta.db_table == "existencia_punto_venta"


def test_una_entrada_por_traslado_suma_y_queda_en_el_libro(punto_venta, producto, gerente):
    movimiento = _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", "30")
    assert existencia_pdv(producto, punto_venta) == Decimal("30")
    assert (movimiento.tipo, movimiento.cantidad) == ("ENTRADA_TRASLADO", Decimal("30"))


def test_una_venta_resta(punto_venta, producto, gerente):
    _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", "30")
    _mover(punto_venta, producto, gerente, "VENTA", "12.5")
    assert existencia_pdv(producto, punto_venta) == Decimal("17.50")


def test_no_se_vende_mas_de_lo_que_hay(punto_venta, producto, gerente):
    """La existencia del PDV nunca queda negativa."""
    _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", "5")
    with pytest.raises(ExistenciaPdvInsuficiente):
        _mover(punto_venta, producto, gerente, "VENTA", "5.01")
    assert existencia_pdv(producto, punto_venta) == Decimal("5")
    assert MovimientoPuntoVenta.objects.count() == 1


def test_solo_se_mueve_inventario_en_un_punto_de_venta(bodega, producto, gerente):
    with pytest.raises(MovimientoPdvInvalido, match="no es un punto de venta"):
        _mover(bodega, producto, gerente, "ENTRADA_TRASLADO", "5")


def test_los_ajustes_no_entran_por_esta_via_todavia(punto_venta, producto, gerente):
    """El ajuste de gerencia en PDV, con su motivo, llega con M8."""
    with pytest.raises(MovimientoPdvInvalido, match="no se registra"):
        _mover(punto_venta, producto, gerente, "AJUSTE_CONTEO", "5")


@pytest.mark.parametrize("cantidad", ["0", "-1", "1.234", "abc"])
def test_la_cantidad_debe_ser_valida(punto_venta, producto, gerente, cantidad):
    with pytest.raises(MovimientoPdvInvalido):
        _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", cantidad)


@pytest.mark.parametrize(
    "cambios",
    [
        {"tipo": "MERMA"},
        {"cantidad": Decimal("0")},
        {"motivo_ajuste": "PERDIDA"},  # el motivo es solo de los ajustes
        {"tipo": "AJUSTE_CONTEO", "motivo_ajuste": "PERDIDA"},  # sin observación
    ],
)
def test_la_base_rechaza_movimientos_incoherentes(punto_venta, producto, gerente, cambios):
    movimiento = _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", "5")
    with pytest.raises(IntegrityError), transaction.atomic():
        MovimientoPuntoVenta.objects.filter(pk=movimiento.pk).update(**cambios)


def test_la_base_impide_existencia_negativa(punto_venta, producto, gerente):
    _mover(punto_venta, producto, gerente, "ENTRADA_TRASLADO", "5")
    with pytest.raises(IntegrityError), transaction.atomic():
        ExistenciaPuntoVenta.objects.filter(producto=producto).update(cantidad=Decimal("-1"))
