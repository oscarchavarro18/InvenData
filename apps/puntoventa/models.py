"""M7 · Punto de venta (RF-46 a RF-49).

En el punto de venta el control deja de ser por lote: en la vitrina es imposible saber de
qué lote sale cada unidad, así que se lleva por producto y cantidad (SN-31). Es el mismo
patrón que la bodega: un libro de movimientos que es la fuente de verdad y una existencia
que es su proyección en vivo (RNF-03). Solo cambia con
`apps.puntoventa.servicios.registrar_movimiento_pdv()`.

Ventas: dos canales con la misma salida de inventario (RF-46, RF-47, RN-33). Al consumidor
final, ligada a la factura que ya generó Siigo (RD-01); al restaurante, con una remisión
propia del sistema y el cliente identificado. Cada línea descuenta de inmediato con un
movimiento VENTA (RN-31). Una venta no se edita ni se borra: se corrige con M8.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.inventario.models import MotivoAjuste
from apps.maestros.models import Cliente, Producto, Ubicacion


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


class VentaConsumidorFinal(ModeloCreacion):
    """Venta a un consumidor final, con el número de la factura que generó Siigo (RF-46)."""

    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="ventas_consumidor"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventas_consumidor"
    )
    fecha = models.DateField()
    numero_factura_siigo = models.CharField(max_length=30, unique=True)

    class Meta:
        db_table = "venta_consumidor_final"
        verbose_name = "venta a consumidor final"
        verbose_name_plural = "ventas a consumidor final"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["ubicacion", "fecha"], name="venta_cf_ubicacion_fecha_idx")]
        constraints = [
            models.CheckConstraint(
                condition=~Q(numero_factura_siigo=""), name="venta_cf_factura_no_vacia"
            )
        ]

    def __str__(self):
        return f"Factura {self.numero_factura_siigo}"


class VentaConsumidorFinalLinea(ModeloCreacion):
    venta_consumidor_final = models.ForeignKey(
        VentaConsumidorFinal, on_delete=models.PROTECT, related_name="lineas"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="lineas_venta_consumidor"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "venta_consumidor_final_linea"
        verbose_name = "línea de venta a consumidor final"
        verbose_name_plural = "líneas de venta a consumidor final"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="venta_cf_linea_cantidad_positiva"
            ),
            models.UniqueConstraint(
                fields=["venta_consumidor_final", "producto"], name="venta_cf_linea_producto_unico"
            ),
        ]

    def __str__(self):
        return f"{self.producto} · {self.cantidad}"


class VentaRestauranteRemision(ModeloCreacion):
    """Venta a un restaurante con remisión propia, sin factura de Siigo (RF-47, RN-33)."""

    numero_documento = models.CharField(max_length=20, unique=True)  # ej. "RM-000012"
    fecha = models.DateField()
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="ventas_restaurante"
    )
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="ventas_restaurante"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventas_restaurante"
    )

    class Meta:
        db_table = "venta_restaurante_remision"
        verbose_name = "venta a restaurante"
        verbose_name_plural = "ventas a restaurante"
        ordering = ["-fecha", "-id"]
        indexes = [
            models.Index(fields=["ubicacion", "fecha"], name="venta_rr_ubicacion_fecha_idx"),
            models.Index(fields=["cliente"], name="venta_rr_cliente_idx"),
        ]

    def __str__(self):
        return f"Remisión {self.numero_documento}"


class VentaRestauranteRemisionLinea(ModeloCreacion):
    venta_restaurante_remision = models.ForeignKey(
        VentaRestauranteRemision, on_delete=models.PROTECT, related_name="lineas"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="lineas_venta_restaurante"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "venta_restaurante_remision_linea"
        verbose_name = "línea de remisión a restaurante"
        verbose_name_plural = "líneas de remisión a restaurante"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="venta_rr_linea_cantidad_positiva"
            ),
            models.UniqueConstraint(
                fields=["venta_restaurante_remision", "producto"],
                name="venta_rr_linea_producto_unico",
            ),
        ]

    def __str__(self):
        return f"{self.producto} · {self.cantidad}"
