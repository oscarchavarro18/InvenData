"""M2 · Recepción de producto (RF-11 a RF-17).

Documento del proveedor (factura o remisión), sus líneas por producto y las tandas de
pesada de cada lote recibido.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.maestros.models import Producto, Proveedor, TipoEmbalaje, Ubicacion


class TipoDocumentoRecepcion(models.TextChoices):
    FACTURA = "FACTURA", "Factura"
    REMISION = "REMISION", "Remisión"


class EstadoDocumento(models.TextChoices):
    ABIERTO = "ABIERTO", "Abierto"
    CERRADO = "CERRADO", "Cerrado"


class DocumentoProveedor(ModeloCreacion):
    """Factura o remisión que trae el proveedor en un viaje (RF-11). Cerrarlo afecta existencias."""

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="documentos")
    tipo_documento = models.CharField(max_length=10, choices=TipoDocumentoRecepcion.choices)
    numero_documento = models.CharField(max_length=30)
    fecha = models.DateField()
    estado = models.CharField(
        max_length=10, choices=EstadoDocumento.choices, default=EstadoDocumento.ABIERTO
    )

    class Meta:
        db_table = "documento_proveedor"
        verbose_name = "documento del proveedor"
        verbose_name_plural = "documentos del proveedor"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["proveedor", "tipo_documento", "numero_documento"],
                name="documento_proveedor_unico",
            ),
            models.CheckConstraint(
                condition=Q(tipo_documento__in=TipoDocumentoRecepcion.values),
                name="documento_proveedor_tipo_valido",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoDocumento.values),
                name="documento_proveedor_estado_valido",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_documento} {self.numero_documento}"


class DocumentoProveedorLinea(ModeloCreacion):
    """Un producto declarado en el documento del proveedor (RF-11, RF-15)."""

    documento_proveedor = models.ForeignKey(
        DocumentoProveedor, on_delete=models.PROTECT, related_name="lineas"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="lineas_recepcion"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)  # declarada en el documento
    cantidad_recibida = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )  # suma pesada; se congela al cerrar
    diferencia_kg = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )  # cantidad - cantidad_recibida; se congela al cerrar

    class Meta:
        db_table = "documento_proveedor_linea"
        verbose_name = "línea del documento del proveedor"
        verbose_name_plural = "líneas del documento del proveedor"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0),
                name="documento_proveedor_linea_cantidad_positiva",
            )
        ]

    def __str__(self):
        return f"Línea de {self.cantidad} (producto {self.producto_id})"


class Recepcion(ModeloCreacion):
    """Una tanda de pesada de un lote recibido (RF-12).

    Un mismo lote puede bajar del camión en varias tandas, cada una con su embalaje,
    su temperatura y su destino. La suma de peso_neto de las tandas del lote es lo que
    se compara contra lo declarado en la remisión al cerrar el documento (RF-13, RF-15).
    """

    lote = models.ForeignKey("inventario.Lote", on_delete=models.PROTECT, related_name="tandas")
    tipo_embalaje = models.ForeignKey(
        TipoEmbalaje, on_delete=models.PROTECT, related_name="tandas_recepcion"
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tandas_recepcion"
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="tandas_recepcion"
    )
    fecha_hora = models.DateTimeField(default=timezone.now)
    cantidad_embalajes = models.PositiveIntegerField()
    peso_bruto = models.DecimalField(max_digits=10, decimal_places=2)
    temperatura = models.DecimalField(max_digits=5, decimal_places=2)
    peso_neto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "recepcion"
        verbose_name = "tanda de recepción"
        verbose_name_plural = "tandas de recepción"
        ordering = ["fecha_hora", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(peso_bruto__gt=0), name="recepcion_peso_bruto_positivo"
            ),
            models.CheckConstraint(
                condition=Q(peso_neto__isnull=True) | Q(peso_neto__gt=0),
                name="recepcion_peso_neto_positivo",
            ),
        ]

    def __str__(self):
        return f"Tanda {self.pk} del lote {self.lote.codigo}"

    def calcular_peso_neto(self):
        """peso_bruto − cantidad_embalajes × tara del tipo de embalaje."""
        bruto = Decimal(str(self.peso_bruto))
        tara = self.tipo_embalaje.peso_tara * int(self.cantidad_embalajes)
        return (bruto - tara).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        # Una tanda no se edita: el peso neto se calcula al crearla y queda fijo, aunque
        # después cambie la tara del tipo de embalaje.
        if self._state.adding:
            self.peso_neto = self.calcular_peso_neto()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "peso_neto"}
        super().save(*args, **kwargs)
