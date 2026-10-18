"""Maestros de M1. Por ahora solo Ubicación, que Usuario necesita (RF-03, RF-05, RF-06).

Pendientes del módulo: proveedor, cliente, categoria_producto, producto, tipo_embalaje, parametro.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import ModeloBase


class TipoUbicacion(models.TextChoices):
    TUNEL_CONGELACION = "TUNEL_CONGELACION", "Túnel de congelación"
    SOSTENIMIENTO = "SOSTENIMIENTO", "Cuarto de sostenimiento"
    ZONA_BULTOS = "ZONA_BULTOS", "Zona de bultos"
    ZONA_TRANSFORMACION = "ZONA_TRANSFORMACION", "Zona de transformación y reempaque"
    PUNTO_VENTA = "PUNTO_VENTA", "Punto de venta"


class Ubicacion(ModeloBase):
    Tipo = TipoUbicacion

    codigo = models.CharField(max_length=30, unique=True)  # estable, lo usa el código
    nombre = models.CharField(max_length=120, unique=True)  # texto para mostrar
    tipo = models.CharField(max_length=30, choices=TipoUbicacion.choices)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "ubicacion"
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"
        ordering = ["codigo"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoUbicacion.values),
                name="ubicacion_tipo_valido",
            )
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"
