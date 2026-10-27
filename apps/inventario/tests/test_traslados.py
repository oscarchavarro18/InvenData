"""Traslados internos entre zonas de la bodega (RF-19, RN-16, RN-18, RF-10)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Lote, Movimiento
from apps.inventario.servicios import (
    ExistenciaInsuficiente,
    MovimientoInvalido,
    existencia_de,
    registrar_movimiento,
    trasladar_entre_zonas,
)
from apps.maestros.models import Ubicacion


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    """El lote con 30 kg en el cuarto de sostenimiento, como tras cerrar su recepción."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="30", usuario=gerente, ubicacion_destino=bodega
    )
    return lote


def test_el_traslado_resta_en_el_origen_y_suma_en_el_destino(en_bodega, bodega, tunel, jefe_bodega):
    movimiento = trasladar_entre_zonas(
        lote=en_bodega,
        origen=bodega,
        destino=tunel,
        cantidad=Decimal("12.50"),
        usuario=jefe_bodega,
        observacion="  Para congelar  ",
    )

    assert movimiento.tipo == "TRASLADO_INTERNO"
    assert movimiento.ubicacion_origen == bodega
    assert movimiento.ubicacion_destino == tunel
    assert movimiento.usuario == jefe_bodega
    assert movimiento.observacion == "Para congelar"
    assert existencia_de(en_bodega, bodega) == Decimal("17.50")
    assert existencia_de(en_bodega, tunel) == Decimal("12.50")


def test_el_traslado_no_cambia_el_estado_del_producto(en_bodega, bodega, tunel, jefe_bodega):
    trasladar_entre_zonas(
        lote=en_bodega, origen=bodega, destino=tunel, cantidad="30", usuario=jefe_bodega
    )
    en_bodega.refresh_from_db()
    assert en_bodega.estado_producto == "FRESCO"


def test_la_observacion_es_opcional(en_bodega, bodega, tunel, gerente):
    movimiento = trasladar_entre_zonas(
        lote=en_bodega, origen=bodega, destino=tunel, cantidad="5", usuario=gerente
    )
    assert movimiento.observacion is None


def test_el_traslado_queda_en_auditoria(en_bodega, bodega, tunel, jefe_bodega):
    movimiento = trasladar_entre_zonas(
        lote=en_bodega,
        origen=bodega,
        destino=tunel,
        cantidad="10",
        usuario=jefe_bodega,
        ip="10.0.0.7",
    )

    (registro,) = Auditoria.objects.filter(entidad="movimiento")
    assert registro.registro_id == movimiento.pk
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.usuario == jefe_bodega
    assert registro.direccion_ip == "10.0.0.7"
    assert registro.valor_nuevo["cantidad"] == "10.00"
    assert registro.valor_nuevo["ubicacion_destino"] == tunel.pk


def test_sin_saldo_suficiente_no_queda_nada(en_bodega, bodega, tunel, jefe_bodega):
    """RN-16: la existencia nunca queda negativa, y si falla no hay movimiento ni rastro."""
    with pytest.raises(ExistenciaInsuficiente):
        trasladar_entre_zonas(
            lote=en_bodega, origen=bodega, destino=tunel, cantidad="30.01", usuario=jefe_bodega
        )
    assert existencia_de(en_bodega, bodega) == Decimal("30")
    assert existencia_de(en_bodega, tunel) == Decimal("0")
    assert not Movimiento.objects.filter(tipo="TRASLADO_INTERNO").exists()
    assert not Auditoria.objects.filter(entidad="movimiento").exists()


def test_no_se_traslada_a_la_misma_zona(en_bodega, bodega, jefe_bodega):
    with pytest.raises(MovimientoInvalido, match="misma ubicación"):
        trasladar_entre_zonas(
            lote=en_bodega, origen=bodega, destino=bodega, cantidad="1", usuario=jefe_bodega
        )


def test_un_punto_de_venta_no_es_destino_de_un_traslado_interno(
    en_bodega, bodega, punto_venta, jefe_bodega
):
    with pytest.raises(MovimientoInvalido, match="punto de venta"):
        trasladar_entre_zonas(
            lote=en_bodega, origen=bodega, destino=punto_venta, cantidad="1", usuario=jefe_bodega
        )
    assert existencia_de(en_bodega, bodega) == Decimal("30")


def test_una_zona_inactiva_no_recibe_producto(en_bodega, bodega, tunel, jefe_bodega):
    Ubicacion.objects.filter(pk=tunel.pk).update(activo=False)
    tunel.refresh_from_db()
    with pytest.raises(MovimientoInvalido, match="inactiva"):
        trasladar_entre_zonas(
            lote=en_bodega, origen=bodega, destino=tunel, cantidad="1", usuario=jefe_bodega
        )


def test_se_puede_vaciar_una_zona_inactiva(en_bodega, bodega, tunel, jefe_bodega):
    Ubicacion.objects.filter(pk=bodega.pk).update(activo=False)
    bodega.refresh_from_db()
    trasladar_entre_zonas(
        lote=en_bodega, origen=bodega, destino=tunel, cantidad="30", usuario=jefe_bodega
    )
    assert existencia_de(en_bodega, bodega) == Decimal("0")


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_gerente_y_jefe_de_bodega_trasladan(request, perfil, en_bodega, bodega, tunel):
    usuario = request.getfixturevalue(perfil)
    with pytest.raises(PermissionDenied):
        trasladar_entre_zonas(
            lote=en_bodega, origen=bodega, destino=tunel, cantidad="1", usuario=usuario
        )
    assert existencia_de(en_bodega, bodega) == Decimal("30")


def test_se_traslada_un_lote_de_inventario_inicial(datos_lote, bodega, tunel, gerente):
    otro = Lote.objects.create(codigo="L-INI", origen="INVENTARIO_INICIAL", **datos_lote)
    registrar_movimiento(
        lote=otro,
        tipo="INVENTARIO_INICIAL",
        cantidad="8",
        usuario=gerente,
        ubicacion_destino=bodega,
    )
    trasladar_entre_zonas(lote=otro, origen=bodega, destino=tunel, cantidad="8", usuario=gerente)
    assert existencia_de(otro, tunel) == Decimal("8")
