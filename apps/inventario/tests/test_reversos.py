from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.inventario.models import Movimiento
from apps.inventario.servicios import (
    ExistenciaInsuficiente,
    MovimientoInvalido,
    existencia_de,
    registrar_movimiento,
    reversar_movimiento,
)


def recibir(lote, ubicacion, cantidad, usuario):
    return registrar_movimiento(
        lote=lote,
        tipo="RECEPCION",
        cantidad=cantidad,
        usuario=usuario,
        ubicacion_destino=ubicacion,
    )


def trasladar(lote, origen, destino, cantidad, usuario, tipo="TRASLADO_INTERNO"):
    return registrar_movimiento(
        lote=lote,
        tipo=tipo,
        cantidad=cantidad,
        usuario=usuario,
        ubicacion_origen=origen,
        ubicacion_destino=destino,
    )


# --- Reversar entradas, salidas y traslados ----------------------------------


def test_reversar_una_recepcion_resta_lo_que_habia_sumado(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)

    (ajuste,) = reversar_movimiento(
        movimiento=original, usuario=gerente, observacion="Se recibió en el lote equivocado"
    )

    assert existencia_de(lote, bodega) == Decimal("0")
    assert ajuste.tipo == "AJUSTE_CONTEO"
    assert ajuste.motivo_ajuste == "ERROR_CONTEO"
    assert ajuste.movimiento_reversado == original
    assert ajuste.cantidad == Decimal("50")
    assert ajuste.ubicacion_origen == bodega
    assert ajuste.ubicacion_destino is None
    assert ajuste.observacion == "Se recibió en el lote equivocado"
    assert ajuste.usuario == gerente


def test_reversar_una_salida_devuelve_lo_que_habia_restado(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    despacho = registrar_movimiento(
        lote=lote,
        tipo="DESPACHO_MAYORISTA",
        cantidad=20,
        usuario=gerente,
        ubicacion_origen=bodega,
    )

    (ajuste,) = reversar_movimiento(
        movimiento=despacho, usuario=gerente, observacion="El despacho se digitó dos veces"
    )

    assert existencia_de(lote, bodega) == Decimal("50")
    assert ajuste.ubicacion_origen is None
    assert ajuste.ubicacion_destino == bodega


@pytest.mark.parametrize("tipo", ["TRASLADO_INTERNO", "EMBULTAJE"])
def test_reversar_un_traslado_genera_dos_ajustes_y_deja_todo_como_estaba(
    tipo, lote, bodega, tunel, gerente
):
    recibir(lote, bodega, 50, gerente)
    traslado = trasladar(lote, bodega, tunel, 30, gerente, tipo)

    ajustes = reversar_movimiento(
        movimiento=traslado, usuario=gerente, observacion="Se trasladó a la zona equivocada"
    )

    assert len(ajustes) == 2
    assert existencia_de(lote, bodega) == Decimal("50")
    assert existencia_de(lote, tunel) == Decimal("0")
    assert {a.movimiento_reversado for a in ajustes} == {traslado}
    assert traslado.reversos.count() == 2


def test_reversar_un_traslado_a_punto_de_venta_solo_devuelve_a_bodega(
    lote, bodega, punto_venta, gerente
):
    recibir(lote, bodega, 50, gerente)
    traslado = trasladar(lote, bodega, punto_venta, 20, gerente, "TRASLADO_PDV")

    (ajuste,) = reversar_movimiento(
        movimiento=traslado, usuario=gerente, observacion="El punto de venta lo rechazó"
    )

    assert existencia_de(lote, bodega) == Decimal("50")
    assert ajuste.ubicacion_destino == bodega
    assert ajuste.ubicacion_origen is None


def test_reversar_un_ajuste_de_conteo_tambien_es_posible(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    ajuste = registrar_movimiento(
        lote=lote,
        tipo="AJUSTE_CONTEO",
        cantidad=3,
        usuario=gerente,
        ubicacion_origen=bodega,
        motivo_ajuste="PERDIDA",
        observacion="Corte de energía",
    )

    reversar_movimiento(movimiento=ajuste, usuario=gerente, observacion="La pérdida no fue real")

    assert existencia_de(lote, bodega) == Decimal("50")


def test_el_movimiento_original_no_se_modifica(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    reversar_movimiento(movimiento=original, usuario=gerente, observacion="Error de captura")

    original.refresh_from_db()
    assert original.tipo == "RECEPCION"
    assert original.cantidad == Decimal("50")
    assert original.movimiento_reversado is None
    assert Movimiento.objects.count() == 2


# --- Reglas del reverso ------------------------------------------------------


def test_un_movimiento_solo_se_reversa_una_vez(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    reversar_movimiento(movimiento=original, usuario=gerente, observacion="Primer reverso")

    with pytest.raises(MovimientoInvalido, match="ya fue reversado"):
        reversar_movimiento(movimiento=original, usuario=gerente, observacion="Segundo intento")
    assert Movimiento.objects.count() == 2


def test_un_reverso_no_se_puede_reversar(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    (ajuste,) = reversar_movimiento(movimiento=original, usuario=gerente, observacion="Error")

    with pytest.raises(MovimientoInvalido, match="no se puede reversar"):
        reversar_movimiento(movimiento=ajuste, usuario=gerente, observacion="Reversar el reverso")
    assert existencia_de(lote, bodega) == Decimal("0")


def test_solo_el_gerente_reversa_movimientos(lote, bodega, gerente, jefe_bodega):
    original = recibir(lote, bodega, 50, gerente)
    with pytest.raises(PermissionDenied):
        reversar_movimiento(movimiento=original, usuario=jefe_bodega, observacion="Sin permiso")
    assert existencia_de(lote, bodega) == Decimal("50")


@pytest.mark.parametrize("observacion", [None, "", "   "])
def test_el_reverso_exige_una_observacion_escrita(observacion, lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="observación"):
        reversar_movimiento(movimiento=original, usuario=gerente, observacion=observacion)
    assert existencia_de(lote, bodega) == Decimal("50")


def test_no_se_reversa_una_recepcion_cuyo_producto_ya_salio(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    registrar_movimiento(
        lote=lote,
        tipo="DESPACHO_MAYORISTA",
        cantidad=40,
        usuario=gerente,
        ubicacion_origen=bodega,
    )

    with pytest.raises(ExistenciaInsuficiente):
        reversar_movimiento(movimiento=original, usuario=gerente, observacion="Quedó poco saldo")

    assert existencia_de(lote, bodega) == Decimal("10")
    assert Movimiento.objects.count() == 2  # la recepción y el despacho, nada más


def test_un_reverso_de_traslado_que_falla_no_deja_nada_a_medias(lote, bodega, tunel, gerente):
    recibir(lote, bodega, 50, gerente)
    traslado = trasladar(lote, bodega, tunel, 30, gerente)
    registrar_movimiento(
        lote=lote,
        tipo="DESPACHO_MAYORISTA",
        cantidad=25,
        usuario=gerente,
        ubicacion_origen=tunel,
    )

    with pytest.raises(ExistenciaInsuficiente):
        reversar_movimiento(movimiento=traslado, usuario=gerente, observacion="Ya se despachó")

    assert existencia_de(lote, bodega) == Decimal("20")
    assert existencia_de(lote, tunel) == Decimal("5")
    assert not Movimiento.objects.filter(movimiento_reversado=traslado).exists()


# --- Lo que la base de datos garantiza por su cuenta -------------------------


def test_la_base_exige_que_un_reverso_sea_un_ajuste_por_error_de_conteo(lote, bodega, gerente):
    original = recibir(lote, bodega, 50, gerente)
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(
            lote=lote,
            tipo="DESPACHO_MAYORISTA",
            cantidad=Decimal("50"),
            usuario=gerente,
            ubicacion_origen=bodega,
            movimiento_reversado=original,
            observacion="Reverso con el tipo equivocado",
        )


@pytest.mark.parametrize("observacion", [None, ""])
def test_la_base_exige_observacion_en_ajustes_y_reversos(observacion, lote, bodega, gerente):
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            motivo_ajuste="OTRO",
            cantidad=Decimal("1"),
            usuario=gerente,
            ubicacion_origen=bodega,
            observacion=observacion,
        )
