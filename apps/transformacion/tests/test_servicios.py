"""Servicio de transformación y balance de masa (RF-23 a RF-29, RN-19 a RN-24)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Lote, Movimiento
from apps.inventario.servicios import existencia_de, registrar_movimiento, trasladar_entre_zonas
from apps.maestros.models import Parametro
from apps.transformacion.models import OrdenTransformacion, TransformacionDerivado
from apps.transformacion.servicios import (
    TransformacionInvalida,
    calcular_balance,
    confirmar_orden,
    crear_orden,
    editar_orden,
    eliminar_orden,
)


def confirmar(orden, derivados, usuario, observacion=None):
    return confirmar_orden(
        orden=orden, derivados=derivados, usuario=usuario, observacion=observacion
    )


# --- Balance de masa ---------------------------------------------------------


@pytest.mark.parametrize(
    ("salidas", "porcentaje", "dentro"),
    [
        (["38"], "95.00", True),  # justo en el límite de 5 %
        (["37.99"], "94.98", False),
        (["40"], "100.00", True),
        (["30", "10.01"], "100.03", False),  # sale más de lo que entra
    ],
)
def test_el_balance_compara_el_cierre_contra_la_tolerancia(salidas, porcentaje, dentro):
    """RF-25, RF-26 y RF-27: salida, merma, porcentaje de cierre y tolerancia."""
    balance = calcular_balance(Decimal("40"), [Decimal(s) for s in salidas], Decimal("5"))
    assert balance.masa_salida == sum(Decimal(s) for s in salidas)
    assert balance.merma_kg == Decimal("40") - balance.masa_salida
    assert balance.porcentaje_cierre == Decimal(porcentaje)
    assert balance.dentro_tolerancia is dentro


# --- Borrador ----------------------------------------------------------------


def test_crear_deja_la_orden_en_borrador_sin_tocar_la_existencia(orden, en_zona, zona):
    """RF-29, RN-21: el borrador no mueve inventario."""
    assert orden.estado == "BORRADOR"
    assert orden.consecutivo == f"OT-{orden.pk:06d}"
    assert orden.cantidad_consumida == Decimal("40")
    assert existencia_de(en_zona, zona) == Decimal("50")
    assert not Movimiento.objects.filter(tipo="CONSUMO_TRANSFORMACION").exists()
    (registro,) = Auditoria.objects.filter(entidad="orden_transformacion")
    assert registro.accion == AccionAuditoria.CREAR


def test_solo_se_transforman_productos_marcados(lote, zona, gerente, jefe_bodega):
    """RF-23: el producto del lote de origen debe admitir transformación."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="10", usuario=gerente, ubicacion_destino=zona
    )
    with pytest.raises(TransformacionInvalida, match="transformable"):
        crear_orden(lote=lote, ubicacion_origen=zona, cantidad_consumida="5", usuario=jefe_bodega)


def test_un_lote_embultado_no_se_transforma(en_zona, zona, jefe_bodega):
    """RN-24: transformar y embultar son caminos excluyentes."""
    Lote.objects.filter(pk=en_zona.pk).update(estado="EMBULTADO")
    with pytest.raises(TransformacionInvalida, match="embultaje"):
        crear_orden(
            lote=en_zona, ubicacion_origen=zona, cantidad_consumida="5", usuario=jefe_bodega
        )


def test_no_se_consume_mas_de_lo_que_hay(en_zona, zona, jefe_bodega):
    with pytest.raises(TransformacionInvalida, match="existencia suficiente"):
        crear_orden(
            lote=en_zona, ubicacion_origen=zona, cantidad_consumida="50.01", usuario=jefe_bodega
        )
    assert not OrdenTransformacion.objects.exists()


@pytest.mark.parametrize("cantidad", ["0", "-1", "1.234", "abc"])
def test_la_cantidad_consumida_debe_ser_valida(cantidad, en_zona, zona, jefe_bodega):
    with pytest.raises(TransformacionInvalida):
        crear_orden(
            lote=en_zona, ubicacion_origen=zona, cantidad_consumida=cantidad, usuario=jefe_bodega
        )


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_gerente_y_jefe_de_bodega_crean_ordenes(request, perfil, en_zona, zona):
    with pytest.raises(PermissionDenied):
        crear_orden(
            lote=en_zona,
            ubicacion_origen=zona,
            cantidad_consumida="5",
            usuario=request.getfixturevalue(perfil),
        )


def test_el_borrador_se_puede_corregir_y_queda_en_auditoria(orden, jefe_bodega):
    editar_orden(orden=orden, cantidad_consumida="45", usuario=jefe_bodega)
    orden.refresh_from_db()
    assert orden.cantidad_consumida == Decimal("45")
    registro = Auditoria.objects.get(accion=AccionAuditoria.MODIFICAR)
    assert registro.valor_anterior["cantidad_consumida"] == "40.00"
    assert registro.valor_nuevo["cantidad_consumida"] == "45.00"


def test_el_borrador_se_puede_eliminar_con_rastro(orden, jefe_bodega):
    orden_id = orden.pk
    eliminar_orden(orden=orden, usuario=jefe_bodega)
    assert not OrdenTransformacion.objects.exists()
    registro = Auditoria.objects.get(accion=AccionAuditoria.ANULAR)
    assert registro.registro_id == orden_id
    assert registro.valor_anterior["cantidad_consumida"] == "40.00"


# --- Confirmación ------------------------------------------------------------


def test_confirmar_descuenta_el_origen_y_crea_un_lote_por_derivado(
    orden, en_zona, zona, tunel, transformable, porciones, derivado, jefe_bodega
):
    """RF-24, RF-25, RF-26, RF-28 y RF-29: la confirmación completa."""
    confirmar(
        orden,
        [derivado("30"), derivado("8", producto=transformable, destino=zona)],
        jefe_bodega,
    )
    orden.refresh_from_db()

    assert orden.estado == "CONFIRMADA"
    assert orden.masa_salida == Decimal("38")
    assert orden.merma_kg == Decimal("2")
    assert orden.porcentaje_cierre == Decimal("95.00")
    assert orden.dentro_tolerancia is True
    assert existencia_de(en_zona, zona) == Decimal("10")  # 50 − 40 consumidos

    porcionado, reempaque = [d.lote_derivado for d in orden.derivados.all()]
    for lote, producto in ((porcionado, porciones), (reempaque, transformable)):
        assert lote.origen == "TRANSFORMACION"
        assert lote.lote_origen == en_zona  # RF-28
        assert lote.producto == producto  # RN-22
        assert lote.codigo == f"L-{lote.pk:06d}"
        assert lote.estado_producto == "CONGELADO"
    assert existencia_de(porcionado, tunel) == Decimal("30")
    assert existencia_de(reempaque, zona) == Decimal("8")
    assert Movimiento.objects.filter(tipo="CONSUMO_TRANSFORMACION").count() == 1
    assert Movimiento.objects.filter(tipo="PRODUCCION_TRANSFORMACION").count() == 2


def test_la_confirmacion_queda_en_auditoria(orden, derivado, jefe_bodega):
    confirmar(orden, [derivado("38")], jefe_bodega)
    assert Auditoria.objects.filter(entidad="transformacion_derivado").count() == 1
    registro = Auditoria.objects.get(entidad="orden_transformacion", accion="MODIFICAR")
    assert registro.valor_anterior["estado"] == "BORRADOR"
    assert registro.valor_nuevo["estado"] == "CONFIRMADA"


def test_fuera_de_tolerancia_sin_observacion_no_confirma_nada(
    orden, en_zona, zona, derivado, jefe_bodega
):
    """RF-27, RN-20: si el cierre se aparta, la observación es obligatoria."""
    with pytest.raises(TransformacionInvalida, match="observación"):
        confirmar(orden, [derivado("30")], jefe_bodega, observacion="   ")
    orden.refresh_from_db()
    assert orden.estado == "BORRADOR"
    assert existencia_de(en_zona, zona) == Decimal("50")
    assert not Lote.objects.filter(origen="TRANSFORMACION").exists()


def test_fuera_de_tolerancia_con_observacion_confirma_y_queda_marcada(orden, derivado, jefe_bodega):
    confirmar(orden, [derivado("30")], jefe_bodega, observacion="Salmón con mucho hueso")
    orden.refresh_from_db()
    assert orden.porcentaje_cierre == Decimal("75.00")
    assert orden.dentro_tolerancia is False
    assert orden.observacion == "Salmón con mucho hueso"


def test_la_tolerancia_la_define_la_gerencia(orden, derivado, jefe_bodega):
    """RF-27, RN-09: el porcentaje sale del parámetro, no del código."""
    Parametro.objects.filter(clave="TOLERANCIA_BALANCE_PCT").update(valor="10")
    confirmar(orden, [derivado("36")], jefe_bodega)  # 90 %
    orden.refresh_from_db()
    assert orden.dentro_tolerancia is True


@pytest.mark.parametrize("valor", ["abc", "-1", "101"])
def test_un_parametro_de_tolerancia_invalido_impide_confirmar(valor, orden, derivado, jefe_bodega):
    Parametro.objects.filter(clave="TOLERANCIA_BALANCE_PCT").update(valor=valor)
    with pytest.raises(TransformacionInvalida, match="porcentaje entre 0 y 100"):
        confirmar(orden, [derivado("38")], jefe_bodega)


def test_sin_parametro_de_tolerancia_no_se_confirma(orden, derivado, jefe_bodega):
    Parametro.objects.filter(clave="TOLERANCIA_BALANCE_PCT").delete()
    with pytest.raises(TransformacionInvalida, match="Falta el parámetro"):
        confirmar(orden, [derivado("38")], jefe_bodega)


def test_sin_derivados_no_se_confirma(orden, jefe_bodega):
    with pytest.raises(TransformacionInvalida, match="al menos un derivado"):
        confirmar(orden, [], jefe_bodega)


def test_un_derivado_no_puede_ir_a_un_punto_de_venta(orden, punto_venta, derivado, jefe_bodega):
    with pytest.raises(TransformacionInvalida, match="zona de bodega"):
        confirmar(orden, [derivado("38", destino=punto_venta)], jefe_bodega)


def test_una_orden_no_se_confirma_dos_veces(orden, derivado, jefe_bodega):
    confirmar(orden, [derivado("38")], jefe_bodega)
    with pytest.raises(TransformacionInvalida, match="ya está confirmada"):
        confirmar(orden, [derivado("38")], jefe_bodega)
    with pytest.raises(TransformacionInvalida, match="ya está confirmada"):
        eliminar_orden(orden=orden, usuario=jefe_bodega)
    assert TransformacionDerivado.objects.count() == 1


def test_si_el_saldo_ya_no_alcanza_no_queda_nada_a_medias(
    orden, en_zona, zona, tunel, derivado, jefe_bodega
):
    """RN-16: alguien movió producto después de crear la orden; la confirmación falla entera."""
    trasladar_entre_zonas(
        lote=en_zona, origen=zona, destino=tunel, cantidad="20", usuario=jefe_bodega
    )
    with pytest.raises(TransformacionInvalida, match="existencia suficiente"):
        confirmar(orden, [derivado("38")], jefe_bodega)
    assert existencia_de(en_zona, zona) == Decimal("30")
    assert not Lote.objects.filter(origen="TRANSFORMACION").exists()
    assert not Movimiento.objects.filter(tipo="CONSUMO_TRANSFORMACION").exists()


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_gerente_y_jefe_de_bodega_confirman(request, perfil, orden, derivado):
    with pytest.raises(PermissionDenied):
        confirmar(orden, [derivado("38")], request.getfixturevalue(perfil))


def test_un_derivado_no_puede_vencer_antes_de_la_orden(orden, derivado, jefe_bodega):
    datos = derivado("38")
    datos["fecha_vencimiento"] = date(2020, 1, 1)
    with pytest.raises(TransformacionInvalida, match="no puede vencer antes"):
        confirmar(orden, [datos], jefe_bodega)


@pytest.mark.parametrize("valor", ["10 %", "10%", " 10,0 "])
def test_la_tolerancia_admite_como_la_escribe_la_gerencia(valor, orden, derivado, jefe_bodega):
    Parametro.objects.filter(clave="TOLERANCIA_BALANCE_PCT").update(valor=valor)
    confirmar(orden, [derivado("36")], jefe_bodega)  # 90 %
    orden.refresh_from_db()
    assert orden.dentro_tolerancia is True


def test_una_masa_de_salida_desbordada_se_rechaza_con_mensaje(
    lote, transformable, zona, porciones, tunel, gerente
):
    """decimal(10,2): la suma de derivados no puede llegar a 100 millones de kg."""
    lote.fecha_vencimiento = timezone.localdate() + timedelta(days=60)
    lote.save(update_fields=["fecha_vencimiento"])
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="90000000", usuario=gerente, ubicacion_destino=zona
    )
    orden = crear_orden(
        lote=lote, ubicacion_origen=zona, cantidad_consumida="90000000", usuario=gerente
    )
    grande = {
        "producto": porciones,
        "ubicacion_destino": tunel,
        "estado_producto": "FRESCO",
        "fecha_vencimiento": lote.fecha_vencimiento,
    }
    derivados = [{**grande, "cantidad": Decimal("60000000")}] * 2
    with pytest.raises(TransformacionInvalida, match="demasiado grande"):
        confirmar(orden, derivados, gerente, observacion="Prueba de límite")
