"""M5 · Embultaje, pedidos y alistamiento (RF-30 a RF-34).

Embultaje: el documento es del día, porque un lote puede embultarse en varias jornadas
(SN-22). Cada registro es una tanda embultada de un lote: solo se pesa lo que queda
embultado (SN-23), y ese total sale del origen y entra al destino con un movimiento
EMBULTAJE. Al cerrar el lote, el residuo que quedó en origen es la merma de embultaje.

Pedidos y alistamiento (pedido, pedido_linea, alistamiento_detalle) llegan en el siguiente
incremento de este mismo módulo.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.inventario.models import Lote
from apps.maestros.models import Ubicacion


class DocumentoEmbultaje(ModeloCreacion):
    """Cabecera del día: un solo documento por fecha, con todos los embultajes de esa jornada."""

    fecha = models.DateField(unique=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="documentos_embultaje"
    )

    class Meta:
        db_table = "documento_embultaje"
        verbose_name = "documento de embultaje"
        verbose_name_plural = "documentos de embultaje"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Embultaje del {self.fecha:%d/%m/%Y}"


class EmbultajeRegistro(ModeloCreacion):
    """Una tanda embultada de un lote dentro del documento del día (RF-30, RN-23, RN-26)."""

    documento_embultaje = models.ForeignKey(
        DocumentoEmbultaje, on_delete=models.PROTECT, related_name="registros"
    )
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="registros_embultaje")
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="embultajes_salida"
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="embultajes_entrada"
    )
    usa_calculo_bultos = models.BooleanField(default=False)
    cantidad_bultos = models.SmallIntegerField(null=True, blank=True)
    peso_por_bulto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_kilos = models.DecimalField(max_digits=10, decimal_places=2)  # lo único que se pesa
    fecha_hora = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registros_embultaje"
    )

    class Meta:
        db_table = "embultaje_registro"
        verbose_name = "registro de embultaje"
        verbose_name_plural = "registros de embultaje"
        ordering = ["fecha_hora", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_kilos__gt=0), name="embultaje_registro_total_positivo"
            ),
            models.CheckConstraint(
                condition=~Q(ubicacion_origen=F("ubicacion_destino")),
                name="embultaje_registro_origen_distinto_destino",
            ),
            # Por bultos: cantidad y peso por bulto, y el total es su producto (RN-26).
            # Digitado: sin cantidad ni peso por bulto. Los isnull=False explícitos evitan que
            # un nulo vuelva la condición NULL, que en un CHECK de SQL cuenta como válida.
            models.CheckConstraint(
                condition=(
                    Q(
                        usa_calculo_bultos=True,
                        cantidad_bultos__isnull=False,
                        peso_por_bulto__isnull=False,
                        cantidad_bultos__gt=0,
                        peso_por_bulto__gt=0,
                        total_kilos=F("cantidad_bultos") * F("peso_por_bulto"),
                    )
                    | Q(
                        usa_calculo_bultos=False,
                        cantidad_bultos__isnull=True,
                        peso_por_bulto__isnull=True,
                    )
                ),
                name="embultaje_registro_modo_coherente",
            ),
        ]

    def __str__(self):
        return f"{self.lote} · {self.total_kilos} kg"


class Bulto(ModeloCreacion):
    """Bulto numerado; solo existe cuando el registro se hizo por cantidad y peso (RF-31, RN-26)."""

    embultaje_registro = models.ForeignKey(
        EmbultajeRegistro, on_delete=models.PROTECT, related_name="bultos"
    )
    consecutivo = models.CharField(max_length=20, unique=True)  # ej. "B-000031"
    peso = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_vencimiento = models.DateField()  # heredada del lote (RF-30)
    rotulo_impreso = models.BooleanField(default=False)  # la impresión queda fuera de alcance

    class Meta:
        db_table = "bulto"
        ordering = ["consecutivo"]
        constraints = [
            models.CheckConstraint(condition=Q(peso__gt=0), name="bulto_peso_positivo"),
        ]

    def __str__(self):
        return self.consecutivo
