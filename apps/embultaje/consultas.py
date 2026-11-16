"""Consultas de lectura del embultaje. Aquí no se modifica nada."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.db.models import OuterRef, Subquery, Sum
from django.utils import timezone

from apps.embultaje.models import AlistamientoDetalle, EstadoPedido
from apps.inventario.models import Existencia, Movimiento, TipoMovimiento
from apps.maestros.models import TipoUbicacion

CERO = Decimal("0")


@dataclass
class ResumenCierre:
    """Lo que pasaría al cerrar el lote como EMBULTADO (vista previa y servicio usan lo mismo).

    - `residuos`: existencia que quedó en las zonas de donde se embultó; al cerrar se da de
      baja como MERMA_EMBULTAJE y su suma es la merma del lote.
    - `embultado`: existencia en las zonas adonde llegó lo embultado; se conserva.
    - `pendiente`: existencia en zonas que nunca fueron origen ni destino de un embultaje.
      Impide cerrar: ese producto no ha pasado por embultaje y no es merma.
    """

    registros: int
    total_embultado: Decimal
    residuos: list = field(default_factory=list)
    embultado: list = field(default_factory=list)
    pendiente: list = field(default_factory=list)

    @property
    def merma(self):
        return sum((e.cantidad for e in self.residuos), CERO)


def resumen_de_cierre(lote):
    registros = lote.registros_embultaje.all()
    origenes = set(registros.values_list("ubicacion_origen_id", flat=True))
    destinos = set(registros.values_list("ubicacion_destino_id", flat=True))
    resumen = ResumenCierre(
        registros=registros.count(),
        total_embultado=registros.aggregate(total=Sum("total_kilos"))["total"] or CERO,
    )
    existencias = (
        Existencia.objects.filter(lote=lote, cantidad__gt=0)
        .select_related("ubicacion")
        .order_by("ubicacion__codigo")
    )
    for existencia in existencias:
        if existencia.ubicacion_id in destinos:
            resumen.embultado.append(existencia)
        elif existencia.ubicacion_id in origenes:
            resumen.residuos.append(existencia)
        else:
            resumen.pendiente.append(existencia)
    return resumen


# De dónde se alista: lo embultado, lo que está en sostenimiento o en el túnel. La zona de
# transformación tiene producto en proceso y el punto de venta no lleva lotes.
UBICACIONES_DE_ALISTAMIENTO = [
    TipoUbicacion.ZONA_BULTOS,
    TipoUbicacion.SOSTENIMIENTO,
    TipoUbicacion.TUNEL_CONGELACION,
]
# Lo planeado en estos pedidos ya está apartado: todavía no sale de bodega pero no se ofrece.
ESTADOS_QUE_COMPROMETEN = [EstadoPedido.CREADO, EstadoPedido.ALISTADO]
TIPOS_DE_ENTRADA = [
    TipoMovimiento.RECEPCION,
    TipoMovimiento.INVENTARIO_INICIAL,
    TipoMovimiento.PRODUCCION_TRANSFORMACION,
]


@dataclass
class Candidato:
    """Un lote en una ubicación, con lo que se puede alistar de él hoy."""

    existencia: Existencia
    entrada: datetime | None
    comprometido: Decimal

    @property
    def lote(self):
        return self.existencia.lote

    @property
    def ubicacion(self):
        return self.existencia.ubicacion

    @property
    def disponible(self):
        return self.existencia.cantidad - self.comprometido

    @property
    def clave(self):
        return f"{self.existencia.lote_id}-{self.existencia.ubicacion_id}"


def comprometido_por_ubicacion(producto):
    """Kg ya apartados, por (lote, ubicación), para un producto.

    Suma lo planeado en pedidos abiertos y lo enviado a un PDV que todavía no se acepta
    (M6): ninguno de los dos se puede ofrecer otra vez.
    """
    from apps.despacho.consultas import comprometido_en_traslados  # M6 depende de M5

    filas = (
        AlistamientoDetalle.objects.filter(
            lote__producto=producto,
            pedido_linea__pedido__estado__in=ESTADOS_QUE_COMPROMETEN,
        )
        .values("lote_id", "ubicacion_id")
        .annotate(total=Sum("cantidad"))
        .order_by()
    )
    comprometido = {(f["lote_id"], f["ubicacion_id"]): f["total"] for f in filas}
    for clave, total in comprometido_en_traslados(lote__producto=producto).items():
        comprometido[clave] = comprometido.get(clave, CERO) + total
    return comprometido


def candidatos_fifo(producto):
    """Lotes del producto que se pueden alistar, del que entró primero al último (RF-33, RN-25).

    El orden es la fecha de entrada a bodega (primer movimiento de entrada del lote), no la
    creación del registro. Se excluyen los vencidos y lo que ya está comprometido en otros
    pedidos; solo quedan los que tienen algo disponible.
    """
    primera_entrada = (
        Movimiento.objects.filter(lote=OuterRef("lote"), tipo__in=TIPOS_DE_ENTRADA)
        .order_by("fecha_hora")
        .values("fecha_hora")[:1]
    )
    existencias = (
        Existencia.objects.filter(
            lote__producto=producto,
            cantidad__gt=0,
            ubicacion__tipo__in=UBICACIONES_DE_ALISTAMIENTO,
            lote__fecha_vencimiento__gte=timezone.localdate(),
        )
        .select_related("lote", "ubicacion")
        .annotate(entrada=Subquery(primera_entrada))
    )
    comprometido = comprometido_por_ubicacion(producto)
    candidatos = [
        Candidato(
            existencia=e,
            entrada=e.entrada,
            comprometido=comprometido.get((e.lote_id, e.ubicacion_id), CERO),
        )
        for e in existencias
    ]
    # Sin fecha de entrada (no debería pasar) va al final; a igual fecha, por código.
    candidatos.sort(
        key=lambda c: (
            c.entrada is None,
            c.entrada.timestamp() if c.entrada else 0,
            c.lote.codigo,
            c.ubicacion.codigo,
        )
    )
    return [c for c in candidatos if c.disponible > CERO]
