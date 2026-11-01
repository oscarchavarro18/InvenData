"""Servicio del levantamiento de inventario inicial (RF-62, RN-01, RN-02, RN-03).

El levantamiento es el único lugar donde se declara producto «de la nada», por eso se cuenta
en borrador y solo el Gerente lo convierte en existencia real. Al aprobar, en una sola
transacción: en bodega se crea un lote LI-xxxxxx por cada fila con su movimiento
INVENTARIO_INICIAL (los que ya estaban embultados nacen cerrados); en un punto de venta, un
movimiento INVENTARIO_INICIAL por producto. Una ubicación que ya opera no se levanta: quedó
arrancada y se corrige con ajustes (SN-08). Toda escritura queda en auditoría (RF-10).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.inventario.models import (
    EstadoLote,
    EstadoProducto,
    Lote,
    Movimiento,
    OrigenLote,
    TipoMovimiento,
)
from apps.inventario.servicios import registrar_movimiento
from apps.levantamiento.models import (
    EstadoLevantamiento,
    InventarioInicial,
    InventarioInicialDetalleLote,
    InventarioInicialDetalleProducto,
)
from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import MovimientoPuntoVenta, TipoMovimientoPdv
from apps.puntoventa.servicios import registrar_movimiento_pdv

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE_KG = Decimal("100000000")  # decimal(10,2)
LIMITE_BULTOS = 32767  # smallint


class ErrorLevantamiento(Exception):
    """Base de los errores por reglas de negocio del levantamiento."""


class LevantamientoInvalido(ErrorLevantamiento):
    """La operación pedida rompe una regla (estado, ubicación, datos...)."""


def es_punto_venta(ubicacion):
    return ubicacion.tipo == TipoUbicacion.PUNTO_VENTA


def puede_registrar(usuario, ubicacion):
    """Bodega la cuenta el Gerente o el Jefe de bodega; un PDV, su administrador o el Gerente."""
    if es_punto_venta(ubicacion):
        return usuario.opera_punto_venta(ubicacion)
    return usuario.puede_operar_bodega


def ve_levantamiento(usuario, ubicacion):
    if es_punto_venta(ubicacion):
        return usuario.ve_punto_venta(ubicacion)
    return usuario.ve_bodega


def ya_opera(ubicacion):
    """Verdadero si la ubicación ya tiene movimientos: entonces quedó arrancada (SN-08)."""
    if es_punto_venta(ubicacion):
        return MovimientoPuntoVenta.objects.filter(ubicacion=ubicacion).exists()
    return Movimiento.objects.filter(ubicacion_origen=ubicacion).exists() or (
        Movimiento.objects.filter(ubicacion_destino=ubicacion).exists()
    )


def _kg(valor, nombre):
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise LevantamientoInvalido(f"{nombre} no es un número válido.") from None
    if not numero.is_finite() or numero != numero.quantize(DOS_DECIMALES):
        raise LevantamientoInvalido(f"{nombre} debe tener como máximo dos decimales.")
    if numero <= CERO:
        raise LevantamientoInvalido(f"{nombre} debe ser mayor que cero.")
    if numero >= LIMITE_KG:
        raise LevantamientoInvalido(f"{nombre} es demasiado grande.")
    return numero


def _auditar(usuario, objeto, accion, ip, *, anterior=None, registro_id=None):
    if accion != AccionAuditoria.ANULAR:
        objeto.refresh_from_db()
    registrar(
        usuario=usuario,
        entidad=objeto._meta.db_table,
        registro_id=registro_id or objeto.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=None if accion == AccionAuditoria.ANULAR else instantanea(objeto),
        ip=ip,
    )


def _registrado(pk, usuario):
    """Relee el levantamiento bloqueándolo: solo se corrige mientras está REGISTRADO."""
    levantamiento = (
        InventarioInicial.objects.select_for_update().select_related("ubicacion").get(pk=pk)
    )
    if not puede_registrar(usuario, levantamiento.ubicacion):
        raise PermissionDenied("No puede modificar el levantamiento de esa ubicación.")
    if levantamiento.estado != EstadoLevantamiento.REGISTRADO:
        raise LevantamientoInvalido("El levantamiento ya fue aprobado: corrija con un ajuste.")
    return levantamiento


@transaction.atomic
def crear_levantamiento(*, ubicacion, usuario, fecha=None, ip=None):
    """Abre el único levantamiento de una ubicación que todavía no opera (RN-02, SN-08)."""
    if not puede_registrar(usuario, ubicacion):
        raise PermissionDenied("No puede registrar el levantamiento de esa ubicación.")
    if not ubicacion.activo:
        raise LevantamientoInvalido(f"{ubicacion.nombre} está inactiva.")
    if InventarioInicial.objects.filter(ubicacion=ubicacion).exists():
        raise LevantamientoInvalido(
            f"{ubicacion.nombre} ya tiene su levantamiento: solo se hace una vez (RN-02)."
        )
    if ya_opera(ubicacion):
        raise LevantamientoInvalido(
            f"{ubicacion.nombre} ya tiene movimientos: quedó arrancada y se corrige con ajustes."
        )
    levantamiento = InventarioInicial.objects.create(
        ubicacion=ubicacion, fecha=fecha or timezone.localdate(), usuario=usuario
    )
    _auditar(usuario, levantamiento, AccionAuditoria.CREAR, ip)
    return levantamiento


@transaction.atomic
def agregar_lote(
    *,
    levantamiento,
    producto,
    estado_producto,
    fecha_vencimiento,
    cantidad,
    usuario,
    estado_lote_resultante=EstadoLote.DISPONIBLE,
    cantidad_bultos=None,
    ip=None,
):
    """Agrega un lote contado en una zona de bodega, todavía sin crear nada (RN-01)."""
    levantamiento = _registrado(levantamiento.pk, usuario)
    if es_punto_venta(levantamiento.ubicacion):
        raise LevantamientoInvalido("En un punto de venta se cuenta por producto, no por lote.")
    if not producto.activo:
        raise LevantamientoInvalido(f"El producto {producto.nombre} está inactivo.")
    if estado_producto not in EstadoProducto.values:
        raise LevantamientoInvalido("El estado del producto debe ser fresco o congelado.")
    if not isinstance(fecha_vencimiento, date):
        raise LevantamientoInvalido("La fecha de vencimiento no es válida.")
    if estado_lote_resultante not in EstadoLote.values:
        raise LevantamientoInvalido("Indique si el lote ya está embultado o no.")
    if cantidad_bultos is not None:
        if estado_lote_resultante != EstadoLote.EMBULTADO:
            raise LevantamientoInvalido("Los bultos solo se indican si ya está embultado.")
        if not isinstance(cantidad_bultos, int) or not 0 <= cantidad_bultos <= LIMITE_BULTOS:
            raise LevantamientoInvalido("Los bultos deben ser un entero entre 0 y 32767.")
    detalle = InventarioInicialDetalleLote.objects.create(
        inventario_inicial=levantamiento,
        producto=producto,
        estado_producto=estado_producto,
        fecha_vencimiento=fecha_vencimiento,
        cantidad=_kg(cantidad, "La cantidad"),
        estado_lote_resultante=estado_lote_resultante,
        cantidad_bultos=cantidad_bultos,
    )
    _auditar(usuario, detalle, AccionAuditoria.CREAR, ip)
    return detalle


@transaction.atomic
def agregar_producto(*, levantamiento, producto, cantidad, usuario, ip=None):
    """Agrega un producto contado en un punto de venta, sin lote (SN-09)."""
    levantamiento = _registrado(levantamiento.pk, usuario)
    if not es_punto_venta(levantamiento.ubicacion):
        raise LevantamientoInvalido("En bodega se cuenta por lote, con su vencimiento.")
    if not producto.activo:
        raise LevantamientoInvalido(f"El producto {producto.nombre} está inactivo.")
    if levantamiento.productos.filter(producto=producto).exists():
        raise LevantamientoInvalido(f"{producto.nombre} ya está en el levantamiento.")
    detalle = InventarioInicialDetalleProducto.objects.create(
        inventario_inicial=levantamiento, producto=producto, cantidad=_kg(cantidad, "La cantidad")
    )
    _auditar(usuario, detalle, AccionAuditoria.CREAR, ip)
    return detalle


@transaction.atomic
def quitar_linea(*, detalle, usuario, ip=None):
    """Quita una fila del borrador; para corregirla se quita y se vuelve a agregar."""
    _registrado(detalle.inventario_inicial_id, usuario)
    anterior, detalle_id = instantanea(detalle), detalle.pk
    detalle.delete()
    _auditar(
        usuario, detalle, AccionAuditoria.ANULAR, ip, anterior=anterior, registro_id=detalle_id
    )


def _crear_lote(detalle, ubicacion, usuario, ahora):
    """Lote de arranque con su existencia; si ya estaba embultado, nace cerrado (RF-62)."""
    lote = Lote.objects.create(
        codigo=f"TMP-{uuid4().hex[:20]}",
        origen=OrigenLote.INVENTARIO_INICIAL,
        producto=detalle.producto,
        estado_producto=detalle.estado_producto,
        fecha_vencimiento=detalle.fecha_vencimiento,
    )
    lote.codigo = f"LI-{lote.pk:06d}"  # distinguible en los reportes, como sugiere el DBML
    lote.save(update_fields=["codigo"])
    registrar_movimiento(
        lote=lote,
        tipo=TipoMovimiento.INVENTARIO_INICIAL,
        cantidad=detalle.cantidad,
        usuario=usuario,
        ubicacion_destino=ubicacion,
    )
    if detalle.estado_lote_resultante == EstadoLote.EMBULTADO:
        # Ya estaba empacado al contar: no hubo embultaje real, así que no hay merma.
        lote.estado = EstadoLote.EMBULTADO
        lote.cerrado_en = ahora
        lote.cerrado_por = usuario
        lote.total_embultado_kg = detalle.cantidad
        lote.save(update_fields=["estado", "cerrado_en", "cerrado_por", "total_embultado_kg"])
    detalle.lote = lote
    detalle.save(update_fields=["lote"])


@transaction.atomic
def aprobar_levantamiento(*, levantamiento, usuario, ip=None):
    """Aprobación del Gerente: el único momento en que el levantamiento crea existencia.

    Solo el Gerente aprueba (RN-01, RN-03). Devuelve el levantamiento aprobado.
    """
    if not usuario.es_gerente:
        raise PermissionDenied("Solo el Gerente aprueba el inventario inicial (RN-03).")
    levantamiento = _registrado(levantamiento.pk, usuario)
    ubicacion = levantamiento.ubicacion
    lotes = list(levantamiento.lotes.select_related("producto"))
    productos = list(levantamiento.productos.select_related("producto"))
    if not lotes and not productos:
        raise LevantamientoInvalido("El levantamiento no tiene nada contado.")
    if ya_opera(ubicacion):
        raise LevantamientoInvalido(
            f"{ubicacion.nombre} empezó a operar mientras se contaba: corrija con ajustes."
        )

    ahora = timezone.now()
    anterior = instantanea(levantamiento)
    for detalle in lotes:
        _crear_lote(detalle, ubicacion, usuario, ahora)
    for detalle in productos:
        registrar_movimiento_pdv(
            ubicacion=ubicacion,
            producto=detalle.producto,
            tipo=TipoMovimientoPdv.INVENTARIO_INICIAL,
            cantidad=detalle.cantidad,
            usuario=usuario,
        )
    levantamiento.estado = EstadoLevantamiento.APROBADO
    levantamiento.usuario_aprueba = usuario
    levantamiento.fecha_hora_aprobacion = ahora
    levantamiento.save(update_fields=["estado", "usuario_aprueba", "fecha_hora_aprobacion"])
    _auditar(usuario, levantamiento, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return levantamiento
