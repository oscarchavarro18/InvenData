"""M0 · Levantamiento de inventario inicial (RF-62).

Módulo de arranque: registra, una sola vez por ubicación, el inventario que ya existía antes
del sistema. En bodega se cuenta por lote (y si ya estaba embultado o no); en un punto de
venta, por producto. Queda REGISTRADO mientras se cuenta y se corrige libremente; solo al
APROBARLO el Gerente se crean los lotes y la existencia real (RN-01 a RN-03). Después la
ubicación queda arrancada: toda corrección es un ajuste de M8, nunca otro levantamiento.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import ModeloCreacion
from apps.inventario.models import EstadoLote, EstadoProducto, Lote
from apps.maestros.models import Producto, Ubicacion


class EstadoLevantamiento(models.TextChoices):
    REGISTRADO = "REGISTRADO", "Registrado"
    APROBADO = "APROBADO", "Aprobado"


class InventarioInicial(ModeloCreacion):
    """Cabecera del único levantamiento de una ubicación (RN-02: uno en toda la vida)."""

    ubicacion = models.OneToOneField(
        Ubicacion, on_delete=models.PROTECT, related_name="inventario_inicial"
    )
    fecha = models.DateField()
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="levantamientos"
    )
    estado = models.CharField(
        max_length=10, choices=EstadoLevantamiento.choices, default=EstadoLevantamiento.REGISTRADO
    )
    usuario_aprueba = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="levantamientos_aprobados",
    )
    fecha_hora_aprobacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inventario_inicial"
        verbose_name = "levantamiento de inventario inicial"
        verbose_name_plural = "levantamientos de inventario inicial"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoLevantamiento.values),
                name="inventario_inicial_estado_valido",
            ),
            # Registrado ⇔ nadie ha aprobado; aprobado ⇔ quién y cuándo (RN-01).
            models.CheckConstraint(
                condition=(
                    Q(
                        estado=EstadoLevantamiento.REGISTRADO,
                        usuario_aprueba__isnull=True,
                        fecha_hora_aprobacion__isnull=True,
                    )
                    | Q(
                        estado=EstadoLevantamiento.APROBADO,
                        usuario_aprueba__isnull=False,
                        fecha_hora_aprobacion__isnull=False,
                    )
                ),
                name="inventario_inicial_aprobacion_completa",
            ),
        ]

    def __str__(self):
        return f"Inventario inicial de {self.ubicacion}"


class InventarioInicialDetalleLote(ModeloCreacion):
    """Un lote que ya existía en una zona de bodega, sin recepción registrada detrás."""

    inventario_inicial = models.ForeignKey(
        InventarioInicial, on_delete=models.PROTECT, related_name="lotes"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="levantamientos_lote"
    )
    estado_producto = models.CharField(max_length=10, choices=EstadoProducto.choices)
    fecha_vencimiento = models.DateField()
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    estado_lote_resultante = models.CharField(
        max_length=10, choices=EstadoLote.choices, default=EstadoLote.DISPONIBLE
    )
    cantidad_bultos = models.SmallIntegerField(null=True, blank=True)  # informativo
    lote = models.ForeignKey(  # se crea al aprobar
        Lote, on_delete=models.PROTECT, null=True, blank=True, related_name="levantamiento"
    )

    class Meta:
        db_table = "inventario_inicial_detalle_lote"
        verbose_name = "lote del inventario inicial"
        verbose_name_plural = "lotes del inventario inicial"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="ii_detalle_lote_cantidad_positiva"
            ),
            models.CheckConstraint(
                condition=Q(estado_producto__in=EstadoProducto.values),
                name="ii_detalle_lote_estado_producto_valido",
            ),
            models.CheckConstraint(
                condition=Q(estado_lote_resultante__in=EstadoLote.values),
                name="ii_detalle_lote_estado_resultante_valido",
            ),
            # Los bultos solo se declaran para lo que ya estaba embultado.
            models.CheckConstraint(
                condition=(
                    Q(cantidad_bultos__isnull=True)
                    | Q(estado_lote_resultante=EstadoLote.EMBULTADO, cantidad_bultos__gte=0)
                ),
                name="ii_detalle_lote_bultos_solo_embultado",
            ),
        ]

    def __str__(self):
        return f"{self.producto} · {self.cantidad} kg"


class InventarioInicialDetalleProducto(ModeloCreacion):
    """Un producto contado en un punto de venta al arrancar, sin lote (SN-09)."""

    inventario_inicial = models.ForeignKey(
        InventarioInicial, on_delete=models.PROTECT, related_name="productos"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name="levantamientos_producto"
    )
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "inventario_inicial_detalle_producto"
        verbose_name = "producto del inventario inicial"
        verbose_name_plural = "productos del inventario inicial"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="ii_detalle_producto_cantidad_positiva"
            ),
            models.UniqueConstraint(
                fields=["inventario_inicial", "producto"], name="ii_detalle_producto_unico"
            ),
        ]

    def __str__(self):
        return f"{self.producto} · {self.cantidad} kg"
