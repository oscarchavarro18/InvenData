"""Parámetros del sistema que el código interpreta (tabla `parametro`, RN-09).

Aquí se define cómo se lee cada uno, para que el panel de gestión valide el valor al
guardarlo y los módulos que lo usan lo interpreten igual.
"""

from decimal import Decimal, InvalidOperation

TOLERANCIA_BALANCE_PCT = "TOLERANCIA_BALANCE_PCT"  # tolerancia de balance de masa (RF-27)

CERO = Decimal("0")
CIEN = Decimal("100")


def leer_porcentaje(valor):
    """Interpreta un porcentaje escrito a mano («5», «2,5», «5 %»). Falla si no está en 0-100."""
    try:
        porcentaje = Decimal(str(valor).strip().rstrip("%").strip().replace(",", "."))
    except InvalidOperation:
        porcentaje = None
    if porcentaje is None or not porcentaje.is_finite() or not CERO <= porcentaje <= CIEN:
        raise ValueError("Debe ser un porcentaje entre 0 y 100.")
    return porcentaje


# Parámetros con un formato conocido y la función que lo valida.
LECTORES = {TOLERANCIA_BALANCE_PCT: leer_porcentaje}
