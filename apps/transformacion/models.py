"""M4 · Transformación y balance de masa (RF-23 a RF-29).

La orden consume parte de un lote de origen y produce uno o varios derivados, cada uno con
su propio lote. Mientras está en BORRADOR solo guarda el encabezado (qué lote, de dónde y
cuánto se consume) y no toca la existencia; al CONFIRMAR se registran los derivados con sus
lotes, los movimientos y el balance de masa, todo de una vez (RF-29, RN-21).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.inventario.models import Lote
from apps.maestros.models import Producto, Ubicacion


class EstadoOrden(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    CONFIRMADA = "CONFIRMADA", "Confirmada"


class OrdenTransformacion(ModeloCreacion):
    consecutivo = models.CharField(max_length=20, unique=True)  # ej. "OT-000012"
    lote_origen = models.ForeignKey(
        Lote, on_delete=models.PROTECT, related_name="ordenes_transformacion"
    )
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="ordenes_transformacion"
    )
    cantidad_consumida = models.DecimalField(max_digits=10, decimal_places=2)  # masa que entra
    # El balance (RF-25 a RF-27) se calcula y se congela al confirmar; en borrador va vacío.
    masa_salida = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    merma_kg = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    porcentaje_cierre = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    dentro_tolerancia = models.BooleanField(null=True, blank=True)
    observacion = models.CharField(max_length=500, null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoOrden.choices, default=EstadoOrden.BORRADOR
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes_transformacion"
    )
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "orden_transformacion"
        verbose_name = "orden de transformación"
        verbose_name_plural = "órdenes de transformación"
        ordering = ["-fecha_hora", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoOrden.values),
                name="orden_transformacion_estado_valido",
            ),
            models.CheckConstraint(
                condition=Q(cantidad_consumida__gt=0),
                name="orden_transformacion_consumo_positivo",
            ),
            models.CheckConstraint(
                condition=(
                    Q(estado=EstadoOrden.BORRADOR)
                    | Q(
                        masa_salida__isnull=False,
                        merma_kg__isnull=False,
                        porcentaje_cierre__isnull=False,
                        dentro_tolerancia__isnull=False,
                    )
                ),
                name="orden_transformacion_confirmada_con_balance",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(dentro_tolerancia=False)
                    | (Q(observacion__isnull=False) & ~Q(observacion=""))
                ),
                name="orden_transformacion_observacion_fuera_tolerancia",
            ),
        ]

    def __str__(self):
        return self.consecutivo


class TransformacionDerivado(ModeloCreacion):
    """Un producto obtenido en la transformación, con el lote que se creó para él (RF-24)."""

    orden = models.ForeignKey(
        OrdenTransformacion, on_delete=models.PROTECT, related_name="derivados"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="derivados_transformacion"
    )
    lote_derivado = models.ForeignKey(
        Lote, on_delete=models.PROTECT, related_name="registros_transformacion"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="derivados_transformacion"
    )

    class Meta:
        db_table = "transformacion_derivado"
        verbose_name = "derivado de transformación"
        verbose_name_plural = "derivados de transformación"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="transformacion_derivado_cantidad_positiva"
            ),
        ]

    def __str__(self):
        return f"{self.orden} → {self.lote_derivado}"
