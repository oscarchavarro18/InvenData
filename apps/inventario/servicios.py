"""Servicio de movimientos de inventario (RF-18 a RF-22).

Es el único camino para mover inventario: cada llamada registra un movimiento en el historial
y actualiza la existencia del lote, todo dentro de una sola transacción. Si cualquier regla
falla no queda nada a medias. Nadie debe escribir en Movimiento o Existencia por otra vía.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.inventario.models import (
    EstadoLote,
    Existencia,
    Lote,
    MotivoAjuste,
    Movimiento,
    TipoMovimiento,
)
from apps.maestros.models import TipoUbicacion

# Qué ubicaciones lleva cada tipo de movimiento (DBML, nota de movimiento.tipo).
SOLO_DESTINO = {
    TipoMovimiento.RECEPCION,
    TipoMovimiento.INVENTARIO_INICIAL,
    TipoMovimiento.PRODUCCION_TRANSFORMACION,
}
SOLO_ORIGEN = {
    TipoMovimiento.CONSUMO_TRANSFORMACION,
    TipoMovimiento.DESPACHO_MAYORISTA,
    TipoMovimiento.MERMA_EMBULTAJE,
}
ORIGEN_Y_DESTINO = {
    TipoMovimiento.TRASLADO_INTERNO,
    TipoMovimiento.EMBULTAJE,
    TipoMovimiento.TRASLADO_PDV,
}
# Los motivos que por definición restan o suman (RF-53).
MOTIVOS_QUE_RESTAN = {MotivoAjuste.PERDIDA, MotivoAjuste.VENCIMIENTO}
MOTIVOS_QUE_SUMAN = {MotivoAjuste.SOBRANTE}

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo


class ErrorInventario(Exception):
    """Base de los errores por reglas de negocio del inventario."""


class MovimientoInvalido(ErrorInventario):
    """El movimiento pedido rompe una regla (ubicaciones, cantidad, motivo...)."""


class ExistenciaInsuficiente(ErrorInventario):
    """Se pidió sacar más de lo que hay: la existencia nunca queda negativa."""


def existencia_de(lote, ubicacion):
    """Cantidad actual del lote en la ubicación; cero si nunca ha tenido existencia ahí."""
    cantidad = (
        Existencia.objects.filter(lote=lote, ubicacion=ubicacion)
        .values_list("cantidad", flat=True)
        .first()
    )
    return CERO if cantidad is None else cantidad


def _validar_cantidad(cantidad):
    try:
        valor = Decimal(str(cantidad))
    except InvalidOperation:
        raise MovimientoInvalido("La cantidad no es un número válido.") from None
    if not valor.is_finite():
        raise MovimientoInvalido("La cantidad no es un número válido.")
    if valor <= CERO:
        raise MovimientoInvalido("La cantidad debe ser mayor que cero.")
    if valor != valor.quantize(DOS_DECIMALES):
        raise MovimientoInvalido("La cantidad admite como máximo dos decimales.")
    if valor >= LIMITE:
        raise MovimientoInvalido("La cantidad es demasiado grande.")
    return valor


def _validar_ubicaciones(tipo, origen, destino):
    if tipo == TipoMovimiento.AJUSTE_CONTEO:
        if (origen is None) == (destino is None):
            raise MovimientoInvalido(
                "Un ajuste de conteo lleva una sola ubicación: destino si suma, origen si resta."
            )
    else:
        pide_origen = tipo in SOLO_ORIGEN or tipo in ORIGEN_Y_DESTINO
        pide_destino = tipo in SOLO_DESTINO or tipo in ORIGEN_Y_DESTINO
        if pide_origen != (origen is not None) or pide_destino != (destino is not None):
            raise MovimientoInvalido(
                f"El tipo {tipo} no lleva esa combinación de ubicación de origen y de destino."
            )
        if tipo in ORIGEN_Y_DESTINO and origen.pk == destino.pk:
            raise MovimientoInvalido("El origen y el destino no pueden ser la misma ubicación.")

    # La existencia por lote solo se lleva en bodega; el punto de venta tiene la suya.
    for ubicacion in (origen, destino):
        if ubicacion is None:
            continue
        es_punto_venta = ubicacion.tipo == TipoUbicacion.PUNTO_VENTA
        if tipo == TipoMovimiento.TRASLADO_PDV and ubicacion is destino:
            if not es_punto_venta:
                raise MovimientoInvalido("El destino de un traslado a punto de venta debe serlo.")
        elif es_punto_venta:
            raise MovimientoInvalido(
                f"{ubicacion.nombre} es un punto de venta: allí no se lleva existencia por lote."
            )


def _validar_ajuste(usuario, motivo, observacion, origen):
    if not usuario.es_gerente:
        raise PermissionDenied("Solo el Gerente puede registrar ajustes de conteo.")
    if motivo not in MotivoAjuste.values:
        raise MovimientoInvalido("El ajuste de conteo exige un motivo de la lista.")
    if observacion is None:
        raise MovimientoInvalido("El ajuste de conteo exige una observación escrita.")
    resta = origen is not None
    if motivo in MOTIVOS_QUE_RESTAN and not resta:
        raise MovimientoInvalido(f"Un ajuste por {motivo} resta: lleva ubicación de origen.")
    if motivo in MOTIVOS_QUE_SUMAN and resta:
        raise MovimientoInvalido(f"Un ajuste por {motivo} suma: lleva ubicación de destino.")


def _aplicar(lote, ubicacion, delta):
    """Suma o resta `delta` a la existencia del lote en la ubicación, bloqueando la fila."""
    bloqueadas = Existencia.objects.select_for_update()
    if delta < CERO:
        try:
            existencia = bloqueadas.get(lote=lote, ubicacion=ubicacion)
        except Existencia.DoesNotExist:
            existencia = None
        disponible = CERO if existencia is None else existencia.cantidad
        if disponible + delta < CERO:
            raise ExistenciaInsuficiente(
                f"No hay existencia suficiente del lote {lote.codigo} en {ubicacion.nombre}: "
                f"disponible {disponible}, solicitado {-delta}."
            )
    else:
        existencia, _ = bloqueadas.get_or_create(
            lote=lote, ubicacion=ubicacion, defaults={"cantidad": CERO}
        )
    existencia.cantidad += delta
    existencia.save(update_fields=["cantidad", "actualizado_en"])


def _crear_movimiento(lote, tipo, cantidad, usuario, origen, destino, extra):
    """Aplica el efecto sobre la existencia y deja el movimiento en el historial."""
    if origen is not None:
        _aplicar(lote, origen, -cantidad)
    # Un traslado a punto de venta solo descuenta en bodega: el destino queda como dato.
    if destino is not None and tipo != TipoMovimiento.TRASLADO_PDV:
        _aplicar(lote, destino, cantidad)
    return Movimiento.objects.create(
        lote=lote,
        tipo=tipo,
        cantidad=cantidad,
        usuario=usuario,
        ubicacion_origen=origen,
        ubicacion_destino=destino,
        **extra,
    )


@transaction.atomic
def registrar_movimiento(
    *,
    lote,
    tipo,
    cantidad,
    usuario,
    ubicacion_origen=None,
    ubicacion_destino=None,
    motivo_ajuste=None,
    observacion=None,
    fecha_hora=None,
):
    """Registra un movimiento y actualiza la existencia. Devuelve el Movimiento creado."""
    if tipo not in TipoMovimiento.values:
        raise MovimientoInvalido(f"El tipo de movimiento {tipo!r} no existe.")
    cantidad = _validar_cantidad(cantidad)
    observacion = (observacion or "").strip() or None
    _validar_ubicaciones(tipo, ubicacion_origen, ubicacion_destino)
    if tipo == TipoMovimiento.AJUSTE_CONTEO:
        _validar_ajuste(usuario, motivo_ajuste, observacion, ubicacion_origen)
    elif motivo_ajuste is not None:
        raise MovimientoInvalido("El motivo de ajuste solo aplica a los ajustes de conteo.")

    # Se bloquea el lote y se relee: así el estado es el real y dos personas no se pisan.
    lote = Lote.objects.select_for_update().get(pk=lote.pk)
    if tipo == TipoMovimiento.EMBULTAJE and lote.estado == EstadoLote.EMBULTADO:
        raise MovimientoInvalido(f"El lote {lote.codigo} ya está embultado.")

    extra = {"motivo_ajuste": motivo_ajuste, "observacion": observacion}
    if fecha_hora is not None:  # si no se indica, el modelo pone la hora actual
        extra["fecha_hora"] = fecha_hora
    return _crear_movimiento(
        lote, tipo, cantidad, usuario, ubicacion_origen, ubicacion_destino, extra
    )
