"""Consultas de lectura sobre el inventario para el tablero y los listados.

Aquí no se modifica nada: el inventario solo cambia a través de `registrar_movimiento`.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.inventario.models import Existencia, Lote

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
