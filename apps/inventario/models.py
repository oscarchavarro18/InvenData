"""M3 · Núcleo de inventario en bodega (RF-18 a RF-22).

Lote (unidad de trazabilidad), movimiento (historial de entradas, salidas y traslados) y
existencia (saldo actual por lote y ubicación). Las reglas que mueven inventario viven en
la capa de servicios; aquí quedan los datos y las restricciones que la base garantiza.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.maestros.models import Producto, Ubicacion


class OrigenLote(models.TextChoices):
    RECEPCION = "RECEPCION", "Recepción"
    TRANSFORMACION = "TRANSFORMACION", "Transformación"
    INVENTARIO_INICIAL = "INVENTARIO_INICIAL", "Inventario inicial"


class EstadoProducto(models.TextChoices):
    FRESCO = "FRESCO", "Fresco"
    CONGELADO = "CONGELADO", "Congelado"


class EstadoLote(models.TextChoices):
    DISPONIBLE = "DISPONIBLE", "Disponible"
    EMBULTADO = "EMBULTADO", "Embultado"


class Lote(ModeloCreacion):
    documento_proveedor_linea = models.ForeignKey(
        "recepcion.DocumentoProveedorLinea",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lotes",
    )
    lote_origen = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="derivados"
    )
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="lotes")
    origen = models.CharField(max_length=20, choices=OrigenLote.choices)
    codigo = models.CharField(max_length=30, unique=True)
    estado_producto = models.CharField(max_length=10, choices=EstadoProducto.choices)
    fecha_vencimiento = models.DateField()
    estado = models.CharField(
        max_length=10, choices=EstadoLote.choices, default=EstadoLote.DISPONIBLE
    )
    cerrado_en = models.DateTimeField(null=True, blank=True)
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lotes_cerrados",
    )
    total_embultado_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    merma_vs_origen_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "lote"
        ordering = ["codigo"]
        indexes = [
            models.Index(fields=["fecha_vencimiento"], name="lote_fecha_vencimiento_idx"),
            models.Index(fields=["estado"], name="lote_estado_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(origen__in=OrigenLote.values), name="lote_origen_valido"
            ),
            models.CheckConstraint(
                condition=Q(estado_producto__in=EstadoProducto.values),
                name="lote_estado_producto_valido",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoLote.values), name="lote_estado_valido"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        origen=OrigenLote.RECEPCION,
                        documento_proveedor_linea__isnull=False,
                        lote_origen__isnull=True,
                    )
                    | Q(
                        origen=OrigenLote.TRANSFORMACION,
                        documento_proveedor_linea__isnull=True,
                        lote_origen__isnull=False,
                    )
                    | Q(
                        origen=OrigenLote.INVENTARIO_INICIAL,
                        documento_proveedor_linea__isnull=True,
                        lote_origen__isnull=True,
                    )
                ),
                name="lote_origen_coherente",
            ),
            models.CheckConstraint(
                condition=~Q(estado=EstadoLote.EMBULTADO, origen=OrigenLote.TRANSFORMACION),
                name="lote_transformado_no_se_embulta",
            ),
        ]

    def __str__(self):
        return self.codigo


class TipoMovimiento(models.TextChoices):
    RECEPCION = "RECEPCION", "Recepción"
    TRASLADO_INTERNO = "TRASLADO_INTERNO", "Traslado interno"
    CONSUMO_TRANSFORMACION = "CONSUMO_TRANSFORMACION", "Consumo por transformación"
    PRODUCCION_TRANSFORMACION = "PRODUCCION_TRANSFORMACION", "Producción por transformación"
    EMBULTAJE = "EMBULTAJE", "Embultaje"
    MERMA_EMBULTAJE = "MERMA_EMBULTAJE", "Merma de embultaje"
    DESPACHO_MAYORISTA = "DESPACHO_MAYORISTA", "Despacho a mayorista"
    TRASLADO_PDV = "TRASLADO_PDV", "Traslado a punto de venta"
    AJUSTE_CONTEO = "AJUSTE_CONTEO", "Ajuste de conteo"
    INVENTARIO_INICIAL = "INVENTARIO_INICIAL", "Inventario inicial"


class MotivoAjuste(models.TextChoices):
    PERDIDA = "PERDIDA", "Pérdida"
    VENCIMIENTO = "VENCIMIENTO", "Vencimiento"
    SOBRANTE = "SOBRANTE", "Sobrante"
    ERROR_CONTEO = "ERROR_CONTEO", "Error de conteo"
    OTRO = "OTRO", "Otro"


class Movimiento(ModeloCreacion):
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=30, choices=TipoMovimiento.choices)
    ubicacion_origen = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimientos_salida",
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movimientos_entrada",
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_hora = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos"
    )
    movimiento_reversado = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversos"
    )
    motivo_ajuste = models.CharField(
        max_length=15, choices=MotivoAjuste.choices, null=True, blank=True
    )
    observacion = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "movimiento"
        ordering = ["-fecha_hora", "-id"]
        indexes = [models.Index(fields=["tipo", "fecha_hora"], name="movimiento_tipo_fecha_idx")]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoMovimiento.values), name="movimiento_tipo_valido"
            ),
            models.CheckConstraint(
                condition=Q(motivo_ajuste__isnull=True) | Q(motivo_ajuste__in=MotivoAjuste.values),
                name="movimiento_motivo_valido",
            ),
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="movimiento_cantidad_positiva"
            ),
            models.CheckConstraint(
                condition=(
                    Q(tipo=TipoMovimiento.AJUSTE_CONTEO, motivo_ajuste__isnull=False)
                    | (~Q(tipo=TipoMovimiento.AJUSTE_CONTEO) & Q(motivo_ajuste__isnull=True))
                ),
                name="movimiento_motivo_solo_en_ajuste",
            ),
            models.CheckConstraint(
                condition=(
                    Q(movimiento_reversado__isnull=True)
                    | Q(tipo=TipoMovimiento.AJUSTE_CONTEO, motivo_ajuste=MotivoAjuste.ERROR_CONTEO)
                ),
                name="movimiento_reverso_es_ajuste_por_error",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(movimiento_reversado__isnull=True) & ~Q(tipo=TipoMovimiento.AJUSTE_CONTEO))
                    | (Q(observacion__isnull=False) & ~Q(observacion=""))
                ),
                name="movimiento_observacion_obligatoria",
            ),
        ]

    def __str__(self):
        return f"{self.tipo} {self.cantidad} (lote {self.lote_id})"


class Existencia(models.Model):
    pk = models.CompositePrimaryKey("lote_id", "ubicacion_id")
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="existencias")
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name="existencias")
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "existencia"
        verbose_name = "existencia"
        verbose_name_plural = "existencias"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gte=0), name="existencia_no_negativa")
        ]

    def __str__(self):
        return f"Lote {self.lote_id} en ubicación {self.ubicacion_id}: {self.cantidad}"
