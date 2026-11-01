"""Consultas de lectura del conteo físico. Aquí no se modifica nada."""

from decimal import Decimal

from django.db.models import Q, Sum

from apps.conteo.models import ConteoFisico
from apps.conteo.servicios import es_punto_venta
from apps.inventario.models import Existencia
from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import ExistenciaPuntoVenta

CERO = Decimal("0")


def conteos_visibles(usuario):
    """Gerente y Consulta ven todos; bodega, los de bodega; un PDV, los suyos (RN-06)."""
    conteos = ConteoFisico.objects.select_related("ubicacion", "usuario")
    if usuario.es_admin_pdv:
        return conteos.filter(ubicacion_id=usuario.ubicacion_id)
    if usuario.ve_algun_punto_venta:  # Gerente y Consulta
        return conteos
    if usuario.ve_bodega:
        return conteos.exclude(ubicacion__tipo=TipoUbicacion.PUNTO_VENTA)
    return conteos.none()


def comparacion(conteo):
    """Lo contado junto a lo que dice hoy el sistema, por producto (RF-52).

    No calcula una diferencia: el conteo es en bultos y el sistema en kg, y la comparación
    es informal a propósito (SN-34). Cada fila trae `detalle` y `kg_sistema`.
    """
    detalles = list(conteo.detalles.select_related("producto"))
    productos = [d.producto_id for d in detalles]
    if es_punto_venta(conteo.ubicacion):
        filas = ExistenciaPuntoVenta.objects.filter(
            ubicacion=conteo.ubicacion, producto_id__in=productos
        ).values_list("producto_id", "cantidad")
        sistema = dict(filas)
    else:
        filas = (
            Existencia.objects.filter(
                Q(ubicacion=conteo.ubicacion) & Q(lote__producto_id__in=productos)
            )
            .values("lote__producto_id")
            .annotate(total=Sum("cantidad"))
            .order_by()
        )
        sistema = {f["lote__producto_id"]: f["total"] for f in filas}
    return [{"detalle": d, "kg_sistema": sistema.get(d.producto_id, CERO)} for d in detalles]
