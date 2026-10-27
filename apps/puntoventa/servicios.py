"""Servicio de movimientos del inventario de punto de venta (RF-48, RN-30, RNF-02, RNF-03).

Es el único camino para mover el inventario de un PDV: cada llamada deja el movimiento en el
libro y actualiza la existencia por producto, en una sola transacción, con el mismo patrón que
`apps.inventario.servicios.registrar_movimiento` en bodega. Nadie debe escribir en
MovimientoPuntoVenta ni en ExistenciaPuntoVenta por otra vía.

Hoy entran los traslados aceptados (ENTRADA_TRASLADO) y el inventario de arranque; las ventas
salen con VENTA. Los ajustes de gerencia (AJUSTE_CONTEO) llegan con M8, que define el sentido
de cada motivo en el punto de venta.
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import ExistenciaPuntoVenta, MovimientoPuntoVenta, TipoMovimientoPdv

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo

# El signo de cada tipo sobre la existencia del PDV (DBML, nota de movimiento_punto_venta).
SUMAN = {TipoMovimientoPdv.ENTRADA_TRASLADO, TipoMovimientoPdv.INVENTARIO_INICIAL}
RESTAN = {TipoMovimientoPdv.VENTA}


class ErrorPuntoVenta(Exception):
    """Base de los errores por reglas de negocio del inventario de punto de venta."""


class MovimientoPdvInvalido(ErrorPuntoVenta):
    """El movimiento pedido rompe una regla (ubicación, tipo, cantidad...)."""


class ExistenciaPdvInsuficiente(ErrorPuntoVenta):
    """Se pidió sacar más de lo que hay: la existencia nunca queda negativa."""


def existencia_pdv(producto, ubicacion):
    """Cantidad actual del producto en el PDV; cero si nunca ha tenido."""
    cantidad = (
        ExistenciaPuntoVenta.objects.filter(producto=producto, ubicacion=ubicacion)
        .values_list("cantidad", flat=True)
        .first()
    )
    return CERO if cantidad is None else cantidad


def _validar_cantidad(cantidad):
    try:
        valor = Decimal(str(cantidad))
    except InvalidOperation:
        raise MovimientoPdvInvalido("La cantidad no es un número válido.") from None
    if not valor.is_finite():
        raise MovimientoPdvInvalido("La cantidad no es un número válido.")
    if valor <= CERO:
        raise MovimientoPdvInvalido("La cantidad debe ser mayor que cero.")
    if valor != valor.quantize(DOS_DECIMALES):
        raise MovimientoPdvInvalido("La cantidad admite como máximo dos decimales.")
    if valor >= LIMITE:
        raise MovimientoPdvInvalido("La cantidad es demasiado grande.")
    return valor


@transaction.atomic
def registrar_movimiento_pdv(*, ubicacion, producto, tipo, cantidad, usuario, fecha_hora=None):
    """Registra un movimiento del PDV y actualiza su existencia. Devuelve el movimiento."""
    if ubicacion.tipo != TipoUbicacion.PUNTO_VENTA:
        raise MovimientoPdvInvalido(f"{ubicacion.nombre} no es un punto de venta.")
    if tipo not in SUMAN | RESTAN:
        raise MovimientoPdvInvalido(f"El tipo {tipo!r} no se registra por esta vía.")
    cantidad = _validar_cantidad(cantidad)
    delta = cantidad if tipo in SUMAN else -cantidad

    # Se bloquea la fila: dos ventas o recepciones a la vez no se pisan.
    existencia, _ = ExistenciaPuntoVenta.objects.select_for_update().get_or_create(
        producto=producto, ubicacion=ubicacion, defaults={"cantidad": CERO}
    )
    if existencia.cantidad + delta < CERO:
        raise ExistenciaPdvInsuficiente(
            f"No hay existencia suficiente de {producto.nombre} en {ubicacion.nombre}: "
            f"disponible {existencia.cantidad}, solicitado {cantidad}."
        )
    existencia.cantidad += delta
    existencia.save(update_fields=["cantidad", "actualizado_en"])

    extra = {} if fecha_hora is None else {"fecha_hora": fecha_hora}
    return MovimientoPuntoVenta.objects.create(
        ubicacion=ubicacion,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        usuario=usuario,
        **extra,
    )
