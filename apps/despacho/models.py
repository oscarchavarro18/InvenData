"""M6 · Despacho mayorista y traslado a punto de venta (RF-35 a RF-45).

Despacho mayorista: el documento que acompaña el furgón de un pedido ya alistado. Se
resuelve en un solo paso (RD-04): al registrarlo, cada línea descuenta la existencia de
bodega de inmediato (RF-36). La firma de quien recibe, en papel fotografiado o trazada en
pantalla, es un respaldo documental posterior, no una condición del descuento (RF-37).

Traslado a punto de venta: bodega envía, el PDV destino verifica quién entrega y cuánto
llega, y decide (RF-38 a RF-45). Solo al aceptar se descuenta bodega y se suma al PDV, en una
transacción (RN-30); si rechaza, nada se mueve, queda el motivo y bodega reenvía un documento
corregido ligado al anterior, hasta que se acepte.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import ModeloCreacion
from apps.embultaje.models import AlistamientoDetalle, Pedido
from apps.inventario.models import Lote
from apps.maestros.models import Ubicacion


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


class EstadoTraslado(models.TextChoices):
    ENVIADO = "ENVIADO", "Enviado"
    ACEPTADO = "ACEPTADO", "Aceptado"
    RECHAZADO = "RECHAZADO", "Rechazado"


class TrasladoPdv(ModeloCreacion):
    """Documento de traslado de bodega a un punto de venta propio (RF-38)."""

    consecutivo = models.CharField(max_length=20, unique=True)  # ej. "T-000004"
    fecha = models.DateField()
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="traslados_pdv_salida"
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="traslados_pdv_entrada"
    )
    usuario_responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="traslados_enviados"
    )
    nombre_entrega = models.CharField(max_length=150)  # quien lo lleva físicamente (RF-41)
    estado = models.CharField(
        max_length=10, choices=EstadoTraslado.choices, default=EstadoTraslado.ENVIADO
    )
    usuario_confirma = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="traslados_confirmados",
    )
    fecha_hora_confirmacion = models.DateTimeField(null=True, blank=True)
    traslado_anterior = models.ForeignKey(  # el rechazado que este corrige (RF-44)
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reenvios"
    )
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "traslado_pdv"
        verbose_name = "traslado a punto de venta"
        verbose_name_plural = "traslados a punto de venta"
        ordering = ["-fecha_hora", "-id"]
        indexes = [
            models.Index(fields=["ubicacion_destino", "estado"], name="traslado_pdv_bandeja_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoTraslado.values), name="traslado_pdv_estado_valido"
            ),
            models.CheckConstraint(
                condition=~Q(ubicacion_origen=F("ubicacion_destino")),
                name="traslado_pdv_origen_distinto_destino",
            ),
            # Enviado ⇔ nadie ha decidido; aceptado o rechazado ⇔ quién y cuándo.
            models.CheckConstraint(
                condition=(
                    Q(
                        estado=EstadoTraslado.ENVIADO,
                        usuario_confirma__isnull=True,
                        fecha_hora_confirmacion__isnull=True,
                    )
                    | (
                        ~Q(estado=EstadoTraslado.ENVIADO)
                        & Q(usuario_confirma__isnull=False, fecha_hora_confirmacion__isnull=False)
                    )
                ),
                name="traslado_pdv_confirmacion_completa",
            ),
            # Un rechazo se corrige con un solo reenvío.
            models.UniqueConstraint(
                fields=["traslado_anterior"], name="traslado_pdv_un_reenvio_por_rechazo"
            ),
        ]

    def __str__(self):
        return self.consecutivo


class TrasladoPdvDetalle(ModeloCreacion):
    """Un lote del traslado: lo declarado al enviar y lo pesado al recibir (RF-40, RF-42)."""

    traslado_pdv = models.ForeignKey(TrasladoPdv, on_delete=models.PROTECT, related_name="detalles")
    lote = models.ForeignKey(Lote, on_delete=models.PROTECT, related_name="traslados_pdv")
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad_verificada = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "traslado_pdv_detalle"
        verbose_name = "detalle de traslado a punto de venta"
        verbose_name_plural = "detalles de traslado a punto de venta"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cantidad__gt=0), name="traslado_pdv_detalle_cantidad_positiva"
            ),
            models.CheckConstraint(
                condition=Q(cantidad_verificada__isnull=True) | Q(cantidad_verificada__gte=0),
                name="traslado_pdv_detalle_verificada_no_negativa",
            ),
            models.UniqueConstraint(
                fields=["traslado_pdv", "lote"], name="traslado_pdv_detalle_lote_unico"
            ),
        ]

    def __str__(self):
        return f"{self.traslado_pdv} · {self.lote} ({self.cantidad} kg)"


class TrasladoPdvObservacion(ModeloCreacion):
    """Historial de notas de un traslado: el motivo del rechazo y lo que digan bodega o
    gerencia al revisarlo (RF-43, RF-44). No se edita ni se borra."""

    traslado_pdv = models.ForeignKey(
        TrasladoPdv, on_delete=models.PROTECT, related_name="observaciones"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="observaciones_traslado"
    )
    observacion = models.CharField(max_length=500)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "traslado_pdv_observacion"
        verbose_name = "observación de traslado"
        verbose_name_plural = "observaciones de traslado"
        ordering = ["fecha_hora", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(observacion=""), name="traslado_pdv_observacion_no_vacia"
            ),
        ]

    def __str__(self):
        return f"{self.traslado_pdv}: {self.observacion[:40]}"
