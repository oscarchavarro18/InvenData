"""Consultas de lectura del punto de venta. Aquí no se modifica nada."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from apps.maestros.models import TipoUbicacion, Ubicacion
from apps.puntoventa.models import (
    MovimientoPuntoVenta,
    SentidoMovimientoPdv,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemisionLinea,
)

CERO = Decimal("0")


def puntos_visibles(usuario):
    """Los puntos de venta que la persona puede ver: el suyo, o todos (RN-06, RN-07)."""
    if usuario.es_admin_pdv:
        return Ubicacion.objects.filter(pk=usuario.ubicacion_id)
    if usuario.ve_algun_punto_venta:
        return Ubicacion.objects.filter(tipo=TipoUbicacion.PUNTO_VENTA).order_by("codigo")
    return Ubicacion.objects.none()


def punto_elegido(usuario, valor):
    """El PDV pedido si la persona puede verlo; si no, el suyo o el primero que ve."""
    puntos = puntos_visibles(usuario)
    elegido = puntos.filter(pk=valor).first() if str(valor).isdigit() else None
    return elegido or puntos.first()


def _rango(desde, hasta):
    """De la medianoche de `desde` a la medianoche siguiente a `hasta`, en la hora local."""
    zona = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(desde, time.min), zona)
    fin = timezone.make_aware(datetime.combine(hasta + timedelta(days=1), time.min), zona)
    return inicio, fin


def historial_pdv(ubicacion, desde, hasta, producto=None):
    """Entradas por traslado y salidas por venta de un PDV en un rango de fechas (RF-49).

    También aparecen los ajustes y reversos del Gerente. Cada movimiento trae `entrada`
    (verdadero si suma) y `reversado` (si ya tiene un reverso); van en orden cronológico.
    """
    inicio, fin = _rango(desde, hasta)
    movimientos = MovimientoPuntoVenta.objects.filter(
        ubicacion=ubicacion, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    if producto is not None:
        movimientos = movimientos.filter(producto=producto)
    reversos = MovimientoPuntoVenta.objects.filter(movimiento_punto_venta_reversado=OuterRef("pk"))
    movimientos = list(
        movimientos.select_related("producto", "usuario")
        .annotate(reversado=Exists(reversos))
        .order_by("fecha_hora", "id")
    )
    for movimiento in movimientos:
        movimiento.entrada = movimiento.sentido == SentidoMovimientoPdv.ENTRADA
    return movimientos


def totales_del_rango(ubicacion, desde, hasta, producto=None):
    """Total que entró y total que salió del punto en el rango (ventas y ajustes)."""
    inicio, fin = _rango(desde, hasta)
    movimientos = MovimientoPuntoVenta.objects.filter(
        ubicacion=ubicacion, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    if producto is not None:
        movimientos = movimientos.filter(producto=producto)

    def total(sentido):
        return movimientos.filter(sentido=sentido).aggregate(t=Sum("cantidad"))["t"] or CERO

    return total(SentidoMovimientoPdv.ENTRADA), total(SentidoMovimientoPdv.SALIDA)


def ventas_del_dia(ubicacion, fecha=None):
    """Cuántas ventas y cuántos kg vendió el punto en el día, por los dos canales."""
    fecha = fecha or timezone.localdate()
    consumidor = VentaConsumidorFinalLinea.objects.filter(
        venta_consumidor_final__ubicacion=ubicacion, venta_consumidor_final__fecha=fecha
    )
    restaurante = VentaRestauranteRemisionLinea.objects.filter(
        venta_restaurante_remision__ubicacion=ubicacion, venta_restaurante_remision__fecha=fecha
    )
    kg = (consumidor.aggregate(t=Sum("cantidad"))["t"] or CERO) + (
        restaurante.aggregate(t=Sum("cantidad"))["t"] or CERO
    )
    cantidad = (
        consumidor.values("venta_consumidor_final").distinct().count()
        + restaurante.values("venta_restaurante_remision").distinct().count()
    )
    return {"ventas": cantidad, "kg": kg}
