"""M7 · Punto de venta (RF-46 a RF-49).

En el punto de venta el control deja de ser por lote: en la vitrina es imposible saber de
qué lote sale cada unidad, así que se lleva por producto y cantidad (SN-31). Es el mismo
patrón que la bodega: un libro de movimientos que es la fuente de verdad y una existencia
que es su proyección en vivo (RNF-03). Solo cambia con
`apps.puntoventa.servicios.registrar_movimiento_pdv()`.

Las ventas (venta_consumidor_final, venta_restaurante_remision y sus líneas) llegan con M7.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.inventario.models import MotivoAjuste
from apps.maestros.models import Producto, Ubicacion


class TipoMovimientoPdv(models.TextChoices):
    ENTRADA_TRASLADO = "ENTRADA_TRASLADO", "Entrada por traslado"
    VENTA = "VENTA", "Venta"
    AJUSTE_CONTEO = "AJUSTE_CONTEO", "Ajuste de conteo"
    INVENTARIO_INICIAL = "INVENTARIO_INICIAL", "Inventario inicial"


class MovimientoPuntoVenta(ModeloCreacion):
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="movimientos_punto_venta"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="movimientos_punto_venta"
    )
    tipo = models.CharField(max_length=20, choices=TipoMovimientoPdv.choices)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)  # el signo lo da el tipo
    fecha_hora = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos_pdv"
    )
    movimiento_punto_venta_reversado = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversos"
    )
    motivo_ajuste = models.CharField(
        max_length=15, choices=MotivoAjuste.choices, null=True, blank=True
    )
    observacion = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "movimiento_punto_venta"
        verbose_name = "movimiento de punto de venta"
        verbose_name_plural = "movimientos de punto de venta"
        ordering = ["-fecha_hora", "-id"]
        indexes = [
            models.Index(
                fields=["ubicacion", "producto", "fecha_hora"],
                name="mov_pdv_ubicacion_producto_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoMovimientoPdv.values), name="mov_pdv_tipo_valido"
            ),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="mov_pdv_cantidad_positiva"),
            models.CheckConstraint(
                condition=Q(motivo_ajuste__isnull=True) | Q(motivo_ajuste__in=MotivoAjuste.values),
                name="mov_pdv_motivo_valido",
            ),
            # El motivo va solo en los ajustes, y todo ajuste lo lleva (RF-53).
            models.CheckConstraint(
                condition=(
                    Q(tipo=TipoMovimientoPdv.AJUSTE_CONTEO, motivo_ajuste__isnull=False)
                    | (~Q(tipo=TipoMovimientoPdv.AJUSTE_CONTEO) & Q(motivo_ajuste__isnull=True))
                ),
                name="mov_pdv_motivo_solo_en_ajuste",
            ),
            # Un ajuste o un reverso se justifica por escrito (RF-09, RN-35).
            models.CheckConstraint(
                condition=(
                    (
                        Q(movimiento_punto_venta_reversado__isnull=True)
                        & ~Q(tipo=TipoMovimientoPdv.AJUSTE_CONTEO)
                    )
                    | (Q(observacion__isnull=False) & ~Q(observacion=""))
                ),
                name="mov_pdv_observacion_obligatoria",
            ),
        ]

    def __str__(self):
        return f"{self.tipo} {self.cantidad} ({self.producto_id} en {self.ubicacion_id})"


class ExistenciaPuntoVenta(models.Model):
    """Cuánto tiene cada punto de venta de cada producto, en tiempo real (RF-48)."""

    pk = models.CompositePrimaryKey("producto_id", "ubicacion_id")
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="existencias_punto_venta"
    )
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="existencias_punto_venta"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "existencia_punto_venta"
        verbose_name = "existencia de punto de venta"
        verbose_name_plural = "existencias de punto de venta"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gte=0), name="existencia_pdv_no_negativa")
        ]

    def __str__(self):
        return f"Producto {self.producto_id} en {self.ubicacion_id}: {self.cantidad}"
