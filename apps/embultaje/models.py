"""M5 · Embultaje, pedidos y alistamiento (RF-30 a RF-34).

Embultaje: el documento es del día, porque un lote puede embultarse en varias jornadas
(SN-22). Cada registro es una tanda embultada de un lote: solo se pesa lo que queda
embultado (SN-23), y ese total sale del origen y entra al destino con un movimiento
EMBULTAJE. Al cerrar el lote, el residuo que quedó en origen es la merma de embultaje.

Pedidos y alistamiento: el pedido de un cliente mayorista tiene una línea por producto, y
cada línea se cubre con uno o varios lotes (RF-34). El alistamiento es un plan de picking:
no toca la existencia; el descuento real ocurre al despachar (M6, RF-36).
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.inventario.models import Lote
from apps.maestros.models import Cliente, Producto, Ubicacion


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


class EstadoPedido(models.TextChoices):
    CREADO = "CREADO", "Creado"
    ALISTADO = "ALISTADO", "Alistado"
    DESPACHADO = "DESPACHADO", "Despachado"
    ANULADO = "ANULADO", "Anulado"


class Pedido(ModeloCreacion):
    """Pedido de un cliente mayorista (RF-32). Anular deja quién, cuándo y por qué."""

    consecutivo = models.CharField(max_length=20, unique=True)  # ej. "P-000007"
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="pedidos")
    fecha = models.DateField()
    estado = models.CharField(
        max_length=12, choices=EstadoPedido.choices, default=EstadoPedido.CREADO
    )
    usuario_crea = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pedidos_creados"
    )
    usuario_alista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pedidos_alistados",
    )
    fecha_hora_alistamiento = models.DateTimeField(null=True, blank=True)
    usuario_anula = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pedidos_anulados",
    )
    fecha_hora_anulacion = models.DateTimeField(null=True, blank=True)
    observacion_anulacion = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "pedido"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoPedido.values), name="pedido_estado_valido"
            ),
            # Quién alistó y cuándo van juntos, y no pueden faltar si ya se alistó o despachó.
            models.CheckConstraint(
                condition=(
                    Q(usuario_alista__isnull=True, fecha_hora_alistamiento__isnull=True)
                    | Q(usuario_alista__isnull=False, fecha_hora_alistamiento__isnull=False)
                ),
                name="pedido_alistamiento_completo",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(estado__in=[EstadoPedido.ALISTADO, EstadoPedido.DESPACHADO])
                    | Q(usuario_alista__isnull=False)
                ),
                name="pedido_alistado_con_responsable",
            ),
            # Anulado ⇔ quién, cuándo y por qué; los isnull=False evitan que un nulo vuelva la
            # condición NULL, que en un CHECK de SQL cuenta como válida.
            models.CheckConstraint(
                condition=(
                    (
                        Q(
                            estado=EstadoPedido.ANULADO,
                            usuario_anula__isnull=False,
                            fecha_hora_anulacion__isnull=False,
                            observacion_anulacion__isnull=False,
                        )
                        & ~Q(observacion_anulacion="")
                    )
                    | (
                        ~Q(estado=EstadoPedido.ANULADO)
                        & Q(
                            usuario_anula__isnull=True,
                            fecha_hora_anulacion__isnull=True,
                            observacion_anulacion__isnull=True,
                        )
                    )
                ),
                name="pedido_anulacion_completa",
            ),
        ]

    def __str__(self):
        return self.consecutivo


class PedidoLinea(ModeloCreacion):
    """Un producto pedido y su cantidad (RF-32). Una sola línea por producto en cada pedido."""

    pedido = models.ForeignKey(Pedido, on_delete=models.PROTECT, related_name="lineas")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="lineas_pedido")
    cantidad_solicitada = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "pedido_linea"
        verbose_name = "línea de pedido"
        verbose_name_plural = "líneas de pedido"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad_solicitada__gt=0), name="pedido_linea_cantidad_positiva"
            ),
            models.UniqueConstraint(
                fields=["pedido", "producto"], name="pedido_linea_producto_unico"
            ),
        ]

    def __str__(self):
        return f"{self.pedido} · {self.producto}"


class AlistamientoDetalle(ModeloCreacion):
    """Qué lote y de qué ubicación cubre una línea del pedido (RF-33, RF-34). No mueve stock."""

    pedido_linea = models.ForeignKey(
        PedidoLinea, on_delete=models.PROTECT, related_name="alistamientos"
    )
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="alistamientos")
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name="alistamientos")
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    sugerido_por_fifo = models.BooleanField()
    justificacion_cambio = models.CharField(max_length=500, null=True, blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "alistamiento_detalle"
        verbose_name = "detalle de alistamiento"
        verbose_name_plural = "detalles de alistamiento"
        ordering = ["fecha_hora", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="alistamiento_detalle_cantidad_positiva"
            ),
            # Elegir un lote distinto del sugerido por FIFO exige justificarlo (RF-33, RN-25).
            models.CheckConstraint(
                condition=(
                    Q(sugerido_por_fifo=True)
                    | (Q(justificacion_cambio__isnull=False) & ~Q(justificacion_cambio=""))
                ),
                name="alistamiento_detalle_justifica_cambio",
            ),
        ]

    def __str__(self):
        return f"{self.pedido_linea} ← {self.lote} ({self.cantidad} kg)"
