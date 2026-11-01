"""M8 · Conteo físico y ajustes (RF-50 a RF-53).

El conteo físico es un hábito de control anterior al sistema y deliberadamente aproximado:
cuenta bultos o cajas por producto, sin lote ni peso exacto, y no genera ningún movimiento
(SN-34, RN-36). El Gerente lo mira junto a lo que dice el sistema y, si encuentra una
diferencia real, la corrige con un ajuste manual justificado (RF-53), que vive en el libro
de movimientos de bodega o del punto de venta, no aquí.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import ModeloCreacion
from apps.maestros.models import Producto, Ubicacion


class ConteoFisico(ModeloCreacion):
    """Jornada de conteo de una ubicación, de bodega o de punto de venta (RF-50)."""

    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name="conteos")
    fecha = models.DateField()
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="conteos"
    )

    class Meta:
        db_table = "conteo_fisico"
        verbose_name = "conteo físico"
        verbose_name_plural = "conteos físicos"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["ubicacion", "fecha"], name="conteo_ubicacion_fecha_idx")]

    def __str__(self):
        return f"Conteo de {self.ubicacion} del {self.fecha:%d/%m/%Y}"


class ConteoFisicoDetalle(ModeloCreacion):
    """Bultos o cajas contados de un producto (RF-51). Sin lote ni diferencia calculada."""

    conteo_fisico = models.ForeignKey(
        ConteoFisico, on_delete=models.PROTECT, related_name="detalles"
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="conteos")
    cantidad_bultos = models.IntegerField()

    class Meta:
        db_table = "conteo_fisico_detalle"
        verbose_name = "detalle de conteo físico"
        verbose_name_plural = "detalles de conteo físico"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad_bultos__gte=0), name="conteo_detalle_bultos_no_negativos"
            ),
            models.UniqueConstraint(
                fields=["conteo_fisico", "producto"], name="conteo_detalle_producto_unico"
            ),
        ]

    def __str__(self):
        return f"{self.producto}: {self.cantidad_bultos} bultos"
