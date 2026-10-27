"""Consultas de lectura sobre el inventario para el tablero y los listados.

Aquí no se modifica nada: el inventario solo cambia a través de `registrar_movimiento`.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Case, Exists, OuterRef, Sum, Value, When
from django.utils import timezone

from apps.inventario.models import Existencia, Lote, Movimiento

# Un lote con existencia que vence dentro de este número de días se considera «por vencer».
# Es provisional: pasará a ser un parámetro de la tabla `parametro` cuando se defina con Pid.
DIAS_POR_VENCER = 7
CERO = Decimal("0")


def lotes_con_existencia():
    """Lotes que todavía tienen producto en alguna ubicación, con su total en kg (`kg`)."""
    return (
        Lote.objects.filter(existencias__cantidad__gt=0)
        .select_related("producto")
        .annotate(kg=Sum("existencias__cantidad"))
    )


def lotes_por_vencer(dias=DIAS_POR_VENCER):
    """Lotes con existencia que vencen en `dias` días o menos (incluye los ya vencidos).

    Cada lote trae `dias_restantes`; negativo significa que ya venció.
    """
    hoy = timezone.localdate()
    limite = hoy + timedelta(days=dias)
    lotes = list(lotes_con_existencia().filter(fecha_vencimiento__lte=limite))
    lotes.sort(key=lambda lote: (lote.fecha_vencimiento, lote.codigo))
    for lote in lotes:
        lote.dias_restantes = (lote.fecha_vencimiento - hoy).days
    return lotes


def kg_en_bodega():
    """Total de kg con existencia positiva en todas las ubicaciones."""
    total = Existencia.objects.filter(cantidad__gt=0).aggregate(total=Sum("cantidad"))["total"]
    return total or CERO


def historial_de_lote(lote):
    """Movimientos del lote en orden cronológico, desde su ingreso hasta su destino final (RF-22).

    Cada movimiento trae `sentido` (ENTRADA, SALIDA o TRASLADO, RN-18) según las ubicaciones
    que lleva, y `reversado`, que indica si ya tiene un reverso (RN-17). Los reversos son
    movimientos más del historial y apuntan al original con `movimiento_reversado`.
    """
    reversos = Movimiento.objects.filter(movimiento_reversado=OuterRef("pk"))
    return (
        lote.movimientos.select_related("usuario", "ubicacion_origen", "ubicacion_destino")
        .annotate(
            sentido=Case(
                When(
                    ubicacion_origen__isnull=False,
                    ubicacion_destino__isnull=False,
                    then=Value("TRASLADO"),
                ),
                When(ubicacion_origen__isnull=True, then=Value("ENTRADA")),
                default=Value("SALIDA"),
            ),
            reversado=Exists(reversos),
        )
        .order_by("fecha_hora", "id")
    )


def existencia_del_lote(lote):
    """Dónde está hoy el lote: sus existencias positivas por ubicación."""
    return (
        lote.existencias.filter(cantidad__gt=0)
        .select_related("ubicacion")
        .order_by("ubicacion__codigo")
    )
