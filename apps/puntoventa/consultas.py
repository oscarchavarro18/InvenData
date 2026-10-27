"""Consultas de lectura del punto de venta. Aquí no se modifica nada."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.maestros.models import TipoUbicacion, Ubicacion
from apps.puntoventa.models import (
    MovimientoPuntoVenta,
    TipoMovimientoPdv,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemisionLinea,
)

CERO = Decimal("0")
# Para el informe del PDV (DBML): entradas suman y ventas restan; aquí no hay traslados.
ENTRADAS = [TipoMovimientoPdv.ENTRADA_TRASLADO, TipoMovimientoPdv.INVENTARIO_INICIAL]


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

    Cada movimiento trae `entrada` (verdadero si suma); van en orden cronológico.
    """
    inicio, fin = _rango(desde, hasta)
    movimientos = MovimientoPuntoVenta.objects.filter(
        ubicacion=ubicacion, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    if producto is not None:
        movimientos = movimientos.filter(producto=producto)
    movimientos = list(
        movimientos.select_related("producto", "usuario").order_by("fecha_hora", "id")
    )
    for movimiento in movimientos:
        movimiento.entrada = movimiento.tipo in ENTRADAS
    return movimientos


def totales_del_rango(ubicacion, desde, hasta, producto=None):
    """Total que entró y total que salió por ventas en el rango."""
    inicio, fin = _rango(desde, hasta)
    movimientos = MovimientoPuntoVenta.objects.filter(
        ubicacion=ubicacion, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    if producto is not None:
        movimientos = movimientos.filter(producto=producto)
    entradas = movimientos.filter(tipo__in=ENTRADAS).aggregate(t=Sum("cantidad"))["t"]
    ventas = movimientos.filter(tipo=TipoMovimientoPdv.VENTA).aggregate(t=Sum("cantidad"))["t"]
    return entradas or CERO, ventas or CERO


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
