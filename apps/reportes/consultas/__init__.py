"""Consultas de los reportes de M9. Aquí no se modifica nada.

- `operacion`: existencias, vencimientos, ventas y correcciones (RF-56 a RF-60).
- `trazabilidad`: el recorrido de punta a punta de un lote (RF-54).
- `mermas`: merma por etapa y acumulada por línea de recepción (RF-55).
- `informe`: informe general por periodo y alcance, con verificación de cuadre (RF-63 a RF-65).
- `indicadores`: indicadores de gestión (RF-61).
"""

from apps.reportes.consultas.comun import periodo_por_defecto
from apps.reportes.consultas.indicadores import indicadores
from apps.reportes.consultas.informe import (
    informe_general,
    opciones_de_alcance,
    resolver_alcance,
)
from apps.reportes.consultas.mermas import mermas
from apps.reportes.consultas.operacion import (
    AGRUPACIONES,
    AMBITOS,
    CANALES,
    correcciones,
    existencias_bodega,
    existencias_pdv,
    por_vencer,
    ventas,
)
from apps.reportes.consultas.trazabilidad import trazabilidad

__all__ = [
    "AGRUPACIONES",
    "AMBITOS",
    "CANALES",
    "correcciones",
    "existencias_bodega",
    "existencias_pdv",
    "indicadores",
    "informe_general",
    "mermas",
    "opciones_de_alcance",
    "periodo_por_defecto",
    "por_vencer",
    "resolver_alcance",
    "trazabilidad",
    "ventas",
]
