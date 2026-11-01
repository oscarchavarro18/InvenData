"""Clasificación automática de cada movimiento según su tipo (RF-64).

Un solo lugar decide si un movimiento es entrada, salida, traslado, merma o ajuste, para que
el informe general, el balance de un lote y los indicadores cuenten lo mismo.
"""

from apps.inventario.models import MotivoAjuste, TipoMovimiento
from apps.puntoventa.models import TipoMovimientoPdv
from apps.reportes.consultas.comun import CERO

ENTRADA = "ENTRADA"
SALIDA = "SALIDA"
TRASLADO = "TRASLADO"
MERMA = "MERMA"
AJUSTE = "AJUSTE"

NOMBRES = {
    ENTRADA: "Entrada",
    SALIDA: "Salida",
    TRASLADO: "Traslado",
    MERMA: "Merma",
    AJUSTE: "Ajuste",
}

# Pérdida y vencimiento son producto que se perdió: cuentan como merma, no como ajuste.
MOTIVOS_DE_MERMA = {MotivoAjuste.PERDIDA, MotivoAjuste.VENCIMIENTO}

_BODEGA = {
    TipoMovimiento.RECEPCION: ENTRADA,
    TipoMovimiento.INVENTARIO_INICIAL: ENTRADA,
    TipoMovimiento.PRODUCCION_TRANSFORMACION: ENTRADA,
    TipoMovimiento.CONSUMO_TRANSFORMACION: SALIDA,
    TipoMovimiento.DESPACHO_MAYORISTA: SALIDA,
    TipoMovimiento.TRASLADO_INTERNO: TRASLADO,
    TipoMovimiento.EMBULTAJE: TRASLADO,  # pasa el producto a la zona de bultos
    TipoMovimiento.TRASLADO_PDV: TRASLADO,
    TipoMovimiento.MERMA_EMBULTAJE: MERMA,
}

_PDV = {
    TipoMovimientoPdv.INVENTARIO_INICIAL: ENTRADA,
    TipoMovimientoPdv.ENTRADA_TRASLADO: TRASLADO,
    TipoMovimientoPdv.VENTA: SALIDA,
}


def clase_bodega(tipo, motivo=None):
    if tipo == TipoMovimiento.AJUSTE_CONTEO:
        return MERMA if motivo in MOTIVOS_DE_MERMA else AJUSTE
    return _BODEGA[tipo]


def clase_pdv(tipo, motivo=None):
    if tipo == TipoMovimientoPdv.AJUSTE_CONTEO:
        return MERMA if motivo in MOTIVOS_DE_MERMA else AJUSTE
    return _PDV[tipo]


def columnas_vacias():
    return dict.fromkeys(("entradas", "salidas", "t_entran", "t_salen", "mermas", "ajustes"), CERO)


def acumular(fila, clase, kg, *, entra, sale):
    """Suma `kg` en la columna que le toca dentro del alcance.

    `entra` y `sale` dicen si el movimiento llega a una ubicación del alcance o sale de una.
    Si hace las dos cosas es un traslado interno: aparece en los dos sentidos y no cambia el
    total. Cualquier combinación rara cae en ajustes con su signo, así el cuadre nunca se
    rompe: final = inicial + entradas - salidas + traslados que entran - traslados que salen
    - mermas + ajustes.
    """
    if entra and sale:
        fila["t_entran"] += kg
        fila["t_salen"] += kg
    elif clase == TRASLADO:
        fila["t_entran" if entra else "t_salen"] += kg
    elif clase == ENTRADA and entra:
        fila["entradas"] += kg
    elif clase == SALIDA and sale:
        fila["salidas"] += kg
    elif clase == MERMA and sale:
        fila["mermas"] += kg
    else:
        fila["ajustes"] += kg if entra else -kg


def neto(fila):
    """El efecto total de las columnas sobre la existencia del alcance."""
    return (
        fila["entradas"]
        - fila["salidas"]
        + fila["t_entran"]
        - fila["t_salen"]
        - fila["mermas"]
        + fila["ajustes"]
    )
