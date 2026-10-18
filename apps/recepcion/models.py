"""M2 · Recepción de producto (RF-11 a RF-17).

Documento del proveedor (factura o remisión) y sus líneas por producto. La tanda de pesada
(tabla recepcion) se agrega después del núcleo de inventario, porque apunta a lote.
"""

from django.db import models
from django.db.models import Q

from apps.core.models import ModeloCreacion
from apps.maestros.models import Producto, Proveedor


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
