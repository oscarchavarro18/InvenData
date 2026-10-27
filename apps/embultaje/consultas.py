"""Consultas de lectura del embultaje. Aquí no se modifica nada."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum

from apps.inventario.models import Existencia

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
