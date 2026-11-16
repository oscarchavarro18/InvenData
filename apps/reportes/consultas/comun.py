"""Piezas compartidas por las consultas de reportes."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

CERO = Decimal("0")
CIEN = Decimal("100")

CONSUMIDOR = "Consumidor final"
RESTAURANTE = "Restaurante"


def porcentaje(parte, total):
    """`parte` como porcentaje de `total`; cero si no hay total."""
    return (parte * CIEN / total) if total else CERO


def periodo(desde, hasta):
    return f"{desde:%d/%m/%Y} a {hasta:%d/%m/%Y}"


def nombres(puntos):
    lista = [p.nombre for p in puntos]
    return ", ".join(lista) if len(lista) <= 3 else f"Todos ({len(lista)})"


def periodo_por_defecto(dias=30):
    """Los últimos `dias` días hasta hoy, para los reportes por periodo."""
    hoy = timezone.localdate()
    return hoy - timedelta(days=dias - 1), hoy
