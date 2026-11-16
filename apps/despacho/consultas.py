"""Consultas de lectura del despacho y del traslado a PDV. Aquí no se modifica nada."""

from django.db.models import F, Sum
from django.utils import timezone

from apps.despacho.models import EstadoTraslado, TrasladoPdvDetalle
from apps.embultaje.consultas import CERO, ESTADOS_QUE_COMPROMETEN, Candidato
from apps.embultaje.models import AlistamientoDetalle
from apps.inventario.models import Existencia


def _sumar(filas):
    return {(f["lote_id"], f["ubicacion_id"]): f["total"] for f in filas}


def comprometido_en_traslados(**filtros):
    """Kg enviados a un PDV que todavía no se aceptan, por (lote, ubicación de origen).

    Ese producto ya salió físicamente de bodega aunque la existencia solo se descuente al
    aceptar (RN-30): no se puede ofrecer a otro pedido ni a otro traslado.
    """
    filas = (
        TrasladoPdvDetalle.objects.filter(traslado_pdv__estado=EstadoTraslado.ENVIADO, **filtros)
        .values("lote_id", ubicacion_id=F("traslado_pdv__ubicacion_origen_id"))
        .annotate(total=Sum("cantidad"))
        .order_by()
    )
    return _sumar(filas)


def candidatos_traslado(origen):
    """Lotes que se pueden enviar desde `origen` a un PDV, con lo disponible de cada uno.

    Disponible es la existencia menos lo apartado en pedidos abiertos y en traslados sin
    aceptar. Se excluyen los vencidos. Primero lo que vence antes.
    """
    alistado = _sumar(
        AlistamientoDetalle.objects.filter(
            ubicacion=origen, pedido_linea__pedido__estado__in=ESTADOS_QUE_COMPROMETEN
        )
        .values("lote_id", "ubicacion_id")
        .annotate(total=Sum("cantidad"))
        .order_by()
    )
    enviado = comprometido_en_traslados(traslado_pdv__ubicacion_origen=origen)
    existencias = (
        Existencia.objects.filter(
            ubicacion=origen,
            cantidad__gt=0,
            lote__fecha_vencimiento__gte=timezone.localdate(),
        )
        .select_related("lote__producto", "ubicacion")
        .order_by("lote__fecha_vencimiento", "lote__codigo")
    )
    candidatos = []
    for existencia in existencias:
        clave = (existencia.lote_id, existencia.ubicacion_id)
        apartado = alistado.get(clave, CERO) + enviado.get(clave, CERO)
        candidato = Candidato(existencia=existencia, entrada=None, comprometido=apartado)
        if candidato.disponible > CERO:
            candidatos.append(candidato)
    return candidatos
