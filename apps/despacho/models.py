"""M6 · Despacho mayorista y traslado a punto de venta (RF-35 a RF-45).

Despacho mayorista: el documento que acompaña el furgón de un pedido ya alistado. Se
resuelve en un solo paso (RD-04): al registrarlo, cada línea descuenta la existencia de
bodega de inmediato (RF-36). La firma de quien recibe, en papel fotografiado o trazada en
pantalla, es un respaldo documental posterior, no una condición del descuento (RF-37).

El traslado a punto de venta (traslado_pdv y sus tablas) llega en el siguiente incremento.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.embultaje.models import AlistamientoDetalle, Pedido


class TipoDocumentoDespacho(models.TextChoices):
    FACTURA = "FACTURA", "Factura"
    REMISION = "REMISION", "Remisión"


class DespachoMayorista(ModeloCreacion):
    """Encabezado del documento del furgón (RF-35). Un pedido se despacha una sola vez."""

    pedido = models.OneToOneField(Pedido, on_delete=models.PROTECT, related_name="despacho")
    fecha_hora = models.DateTimeField(default=timezone.now)
    placa_vehiculo = models.CharField(max_length=10)
    numero_sello = models.CharField(max_length=30, null=True, blank=True)
    nombre_conductor = models.CharField(max_length=150)
    tipo_documento = models.CharField(max_length=10, choices=TipoDocumentoDespacho.choices)
    numero_documento = models.CharField(max_length=30)
    valor_total = models.DecimalField(  # informativo: no reemplaza a Siigo (RD-01)
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    usuario_despacha = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="despachos"
    )
    # Constancia de entrega (RF-37): se llena después, cuando el cliente firma.
    nombre_recibe = models.CharField(max_length=150, null=True, blank=True)
    firma_recibe_digital = models.JSONField(null=True, blank=True)  # trazos de la firma
    fecha_hora_recepcion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "despacho_mayorista"
        verbose_name = "despacho mayorista"
        verbose_name_plural = "despachos mayoristas"
        ordering = ["-fecha_hora", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo_documento__in=TipoDocumentoDespacho.values),
                name="despacho_mayorista_tipo_valido",
            ),
            models.UniqueConstraint(
                fields=["tipo_documento", "numero_documento"],
                name="despacho_mayorista_documento_unico",
            ),
            models.CheckConstraint(
                condition=Q(valor_total__isnull=True) | Q(valor_total__gte=0),
                name="despacho_mayorista_valor_no_negativo",
            ),
            # Quién recibió y cuándo van juntos; la firma digital solo existe si hay entrega.
            models.CheckConstraint(
                condition=(
                    Q(
                        nombre_recibe__isnull=True,
                        fecha_hora_recepcion__isnull=True,
                        firma_recibe_digital__isnull=True,
                    )
                    | (
                        Q(nombre_recibe__isnull=False, fecha_hora_recepcion__isnull=False)
                        & ~Q(nombre_recibe="")
                    )
                ),
                name="despacho_mayorista_entrega_completa",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_documento} {self.numero_documento}"


class DespachoDetalle(ModeloCreacion):
    """Una línea del documento: lo que realmente se cargó de un lote alistado (RF-35, RF-36)."""

    despacho_mayorista = models.ForeignKey(
        DespachoMayorista, on_delete=models.PROTECT, related_name="detalles"
    )
    alistamiento_detalle = models.ForeignKey(
        AlistamientoDetalle, on_delete=models.PROTECT, related_name="despachos"
    )
    cantidad_bultos_cajas = models.SmallIntegerField(null=True, blank=True)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)  # lo que descuenta

    class Meta:
        db_table = "despacho_detalle"
        verbose_name = "detalle de despacho"
        verbose_name_plural = "detalles de despacho"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="despacho_detalle_cantidad_positiva"
            ),
            models.CheckConstraint(
                condition=Q(cantidad_bultos_cajas__isnull=True) | Q(cantidad_bultos_cajas__gte=0),
                name="despacho_detalle_bultos_no_negativos",
            ),
            # Cada lote alistado sale una sola vez.
            models.UniqueConstraint(
                fields=["alistamiento_detalle"], name="despacho_detalle_alistamiento_unico"
            ),
        ]

    def __str__(self):
        return f"{self.despacho_mayorista} · {self.cantidad} kg"
