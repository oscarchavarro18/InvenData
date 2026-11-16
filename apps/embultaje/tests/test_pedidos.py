"""Pedidos y alistamiento con sugerencia FIFO (RF-32, RF-33, RF-34, RN-25)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.embultaje.consultas import candidatos_fifo
from apps.embultaje.models import AlistamientoDetalle, Pedido, PedidoLinea
from apps.embultaje.servicios import (
    EmbultajeInvalido,
    agregar_linea,
    anular_pedido,
    asignar_lote,
    crear_pedido,
    marcar_alistado,
    quitar_alistamiento,
    quitar_linea,
    sugerir_fifo,
)
from apps.inventario.models import Existencia
from apps.maestros.models import Cliente, Producto, Ubicacion


@pytest.fixture
def lotes(con_existencia, zona_bultos, bodega):
    """El viejo (40 kg, entró hace 10 días) va antes que el nuevo (50 kg, hace 2 días)."""
    viejo = con_existencia("L-VIEJO", "40", zona_bultos, dias=10)
    nuevo = con_existencia("L-NUEVO", "50", bodega, dias=2)
    return viejo, nuevo


@pytest.fixture
def linea(pedido):
    return pedido.lineas.get()


def _existencias():
    return {(e.lote_id, e.ubicacion_id): e.cantidad for e in Existencia.objects.all()}


# --- Pedido y líneas ---------------------------------------------------------


def test_crear_un_pedido_con_su_linea_queda_en_auditoria(pedido):
    """RF-32."""
    assert pedido.estado == "CREADO"
    assert pedido.consecutivo == f"P-{pedido.pk:06d}"
    assert pedido.lineas.get().cantidad_solicitada == Decimal("60")
    assert Auditoria.objects.filter(entidad="pedido", accion=AccionAuditoria.CREAR).exists()
    assert Auditoria.objects.filter(entidad="pedido_linea").exists()


def test_un_cliente_inactivo_no_hace_pedidos(cliente, jefe_bodega):
    Cliente.objects.filter(pk=cliente.pk).update(activo=False)
    cliente.refresh_from_db()
    with pytest.raises(EmbultajeInvalido, match="inactivo"):
        crear_pedido(cliente=cliente, fecha=timezone.localdate(), usuario=jefe_bodega)


def test_una_sola_linea_por_producto(pedido, producto, jefe_bodega):
    with pytest.raises(EmbultajeInvalido, match="ya tiene una línea"):
        agregar_linea(
            pedido=pedido, producto=producto, cantidad_solicitada="5", usuario=jefe_bodega
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        PedidoLinea.objects.create(pedido=pedido, producto=producto, cantidad_solicitada=5)


def test_una_linea_con_lotes_no_se_quita(pedido, linea, lotes, jefe_bodega):
    sugerir_fifo(linea=linea, usuario=jefe_bodega)
    with pytest.raises(EmbultajeInvalido, match="Quite primero"):
        quitar_linea(linea=linea, usuario=jefe_bodega)
    AlistamientoDetalle.objects.all().delete()
    quitar_linea(linea=linea, usuario=jefe_bodega)
    assert not pedido.lineas.exists()


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_bodega_crea_pedidos(request, perfil, cliente):
    with pytest.raises(PermissionDenied):
        crear_pedido(
            cliente=cliente, fecha=timezone.localdate(), usuario=request.getfixturevalue(perfil)
        )


# --- FIFO --------------------------------------------------------------------


def test_fifo_ordena_por_fecha_de_entrada(lotes, producto):
    """RF-33, RN-25: el que entró primero va primero, sin importar su código."""
    viejo, nuevo = lotes
    assert [c.lote for c in candidatos_fifo(producto)] == [viejo, nuevo]


def test_fifo_excluye_vencidos_y_producto_en_proceso(con_existencia, lotes, producto, zona_bultos):
    viejo, nuevo = lotes
    zona = Ubicacion.objects.create(
        codigo="TRF-01", nombre="Zona de transformación", tipo="ZONA_TRANSFORMACION"
    )
    con_existencia("L-VENCIDO", "30", zona_bultos, dias=30, vence_en=-1)
    con_existencia("L-PROCESO", "30", zona, dias=40)
    assert [c.lote for c in candidatos_fifo(producto)] == [viejo, nuevo]


def test_sugerir_fifo_cubre_con_varios_lotes_sin_tocar_la_existencia(linea, lotes, jefe_bodega):
    """RF-34: si el más antiguo no alcanza, se completa con el siguiente; no es un descuento."""
    viejo, nuevo = lotes
    antes = _existencias()

    detalles = sugerir_fifo(linea=linea, usuario=jefe_bodega)

    assert [(d.lote, d.cantidad, d.sugerido_por_fifo) for d in detalles] == [
        (viejo, Decimal("40"), True),
        (nuevo, Decimal("20"), True),
    ]
    assert _existencias() == antes


def test_lo_comprometido_en_otro_pedido_no_se_ofrece(
    pedido, linea, lotes, cliente, producto, jefe_bodega
):
    viejo, nuevo = lotes
    sugerir_fifo(linea=linea, usuario=jefe_bodega)  # aparta 40 del viejo y 20 del nuevo

    candidatos = candidatos_fifo(producto)

    assert [(c.lote, c.disponible) for c in candidatos] == [(nuevo, Decimal("30"))]


def test_anular_libera_lo_comprometido(pedido, linea, lotes, producto, jefe_bodega, gerente):
    sugerir_fifo(linea=linea, usuario=jefe_bodega)
    anular_pedido(pedido=pedido, usuario=gerente, observacion="El cliente canceló")
    assert [c.disponible for c in candidatos_fifo(producto)] == [Decimal("40"), Decimal("50")]


def test_sin_existencia_disponible_avisa(linea, jefe_bodega):
    with pytest.raises(EmbultajeInvalido, match="No hay Pechuga disponible"):
        sugerir_fifo(linea=linea, usuario=jefe_bodega)


# --- Elegir el lote a mano ---------------------------------------------------


def test_usar_el_sugerido_no_pide_justificacion(linea, lotes, zona_bultos, jefe_bodega):
    viejo, _ = lotes
    detalle = asignar_lote(
        linea=linea, lote=viejo, ubicacion=zona_bultos, cantidad="25", usuario=jefe_bodega
    )
    assert detalle.sugerido_por_fifo is True
    assert detalle.justificacion_cambio is None


def test_otro_lote_exige_justificacion(linea, lotes, bodega, jefe_bodega):
    """RF-33, RN-25: elegir distinto del FIFO solo si se justifica por escrito."""
    _, nuevo = lotes
    with pytest.raises(EmbultajeInvalido, match="FIFO sugiere el lote L-VIEJO"):
        asignar_lote(linea=linea, lote=nuevo, ubicacion=bodega, cantidad="20", usuario=jefe_bodega)

    detalle = asignar_lote(
        linea=linea,
        lote=nuevo,
        ubicacion=bodega,
        cantidad="20",
        usuario=jefe_bodega,
        justificacion="El cliente lo pidió fresco de sostenimiento",
    )
    assert detalle.sugerido_por_fifo is False
    assert detalle.justificacion_cambio == "El cliente lo pidió fresco de sostenimiento"


def test_la_base_exige_la_justificacion(linea, lotes, zona_bultos, jefe_bodega):
    detalle = asignar_lote(
        linea=linea, lote=lotes[0], ubicacion=zona_bultos, cantidad="5", usuario=jefe_bodega
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AlistamientoDetalle.objects.filter(pk=detalle.pk).update(sugerido_por_fifo=False)


def test_no_se_aparta_mas_de_lo_disponible_ni_de_lo_pendiente(
    linea, lotes, zona_bultos, jefe_bodega
):
    viejo, _ = lotes
    with pytest.raises(EmbultajeInvalido, match="solo hay 40.00 kg disponibles"):
        asignar_lote(
            linea=linea, lote=viejo, ubicacion=zona_bultos, cantidad="45", usuario=jefe_bodega
        )
    with pytest.raises(EmbultajeInvalido, match="solo le faltan 60.00 kg"):
        asignar_lote(
            linea=linea, lote=viejo, ubicacion=zona_bultos, cantidad="61", usuario=jefe_bodega
        )


def test_un_lote_de_otro_producto_no_cubre_la_linea(
    linea, con_existencia, datos_lote, bodega, jefe_bodega
):
    otro_producto = Producto.objects.create(
        codigo="PES-001",
        nombre="Tilapia",
        unidad_medida="KG",
        categoria=datos_lote["producto"].categoria,
    )
    otro = con_existencia("L-OTRO", "10", bodega)
    otro.producto = otro_producto
    otro.save(update_fields=["producto"])
    with pytest.raises(EmbultajeInvalido, match="no es de Pechuga"):
        asignar_lote(linea=linea, lote=otro, ubicacion=bodega, cantidad="5", usuario=jefe_bodega)


def test_un_lote_vencido_no_se_alista(linea, con_existencia, bodega, jefe_bodega):
    vencido = con_existencia("L-VENCIDO", "10", bodega, vence_en=-1)
    with pytest.raises(EmbultajeInvalido, match="vencido"):
        asignar_lote(linea=linea, lote=vencido, ubicacion=bodega, cantidad="5", usuario=jefe_bodega)


# --- Alistado y anulación ----------------------------------------------------


def test_marcar_alistado_exige_lotes_en_cada_linea(pedido, jefe_bodega):
    with pytest.raises(EmbultajeInvalido, match="Falta asignar lotes a: Pechuga"):
        marcar_alistado(pedido=pedido, usuario=jefe_bodega)


def test_alistado_con_cobertura_parcial_y_sin_tocar_existencia(
    pedido, linea, lotes, zona_bultos, jefe_bodega
):
    """RF-34: lo pesado no siempre cuadra; se alista con lo asignado."""
    asignar_lote(
        linea=linea, lote=lotes[0], ubicacion=zona_bultos, cantidad="40", usuario=jefe_bodega
    )
    antes = _existencias()

    marcar_alistado(pedido=pedido, usuario=jefe_bodega)

    pedido.refresh_from_db()
    assert pedido.estado == "ALISTADO"
    assert pedido.usuario_alista == jefe_bodega
    assert pedido.fecha_hora_alistamiento is not None
    assert _existencias() == antes
    registro = Auditoria.objects.get(entidad="pedido", accion=AccionAuditoria.MODIFICAR)
    assert registro.valor_nuevo["estado"] == "ALISTADO"


def test_un_pedido_alistado_ya_no_cambia(pedido, linea, lotes, producto, jefe_bodega):
    detalle = sugerir_fifo(linea=linea, usuario=jefe_bodega)[0]
    marcar_alistado(pedido=pedido, usuario=jefe_bodega)
    with pytest.raises(EmbultajeInvalido, match="ya no admite cambios"):
        quitar_alistamiento(detalle=detalle, usuario=jefe_bodega)
    with pytest.raises(EmbultajeInvalido, match="ya no admite cambios"):
        agregar_linea(
            pedido=pedido, producto=producto, cantidad_solicitada="1", usuario=jefe_bodega
        )


def test_solo_el_gerente_anula_y_con_motivo(pedido, jefe_bodega, gerente):
    with pytest.raises(PermissionDenied):
        anular_pedido(pedido=pedido, usuario=jefe_bodega, observacion="Error")
    with pytest.raises(EmbultajeInvalido, match="por qué"):
        anular_pedido(pedido=pedido, usuario=gerente, observacion="   ")

    anular_pedido(pedido=pedido, usuario=gerente, observacion="Pedido duplicado")

    pedido.refresh_from_db()
    assert pedido.estado == "ANULADO"
    assert (pedido.usuario_anula, pedido.observacion_anulacion) == (gerente, "Pedido duplicado")
    with pytest.raises(EmbultajeInvalido, match="no se puede anular"):
        anular_pedido(pedido=pedido, usuario=gerente, observacion="Otra vez")


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "ANULADO"},  # sin quién, cuándo ni por qué
        {"estado": "ALISTADO"},  # sin quién alistó
        {"observacion_anulacion": "Motivo sin anular"},
    ],
)
def test_la_base_rechaza_pedidos_incoherentes(pedido, cambios):
    with pytest.raises(IntegrityError), transaction.atomic():
        Pedido.objects.filter(pk=pedido.pk).update(**cambios)
