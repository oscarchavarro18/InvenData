import pytest

from apps.embultaje.servicios import registrar_embultaje
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import Ubicacion


@pytest.fixture
def zona_bultos(db):
    return Ubicacion.objects.create(codigo="BUL-01", nombre="Zona de bultos", tipo="ZONA_BULTOS")


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    """El lote con 100 kg en el cuarto de sostenimiento, como tras cerrar su recepción."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="100", usuario=gerente, ubicacion_destino=bodega
    )
    lote.refresh_from_db()
    return lote


@pytest.fixture
def embultar(en_bodega, bodega, zona_bultos, jefe_bodega):
    """Registra un embultaje del lote de sostenimiento a la zona de bultos; acepta cambios."""

    def hacer(**cambios):
        datos = {
            "lote": en_bodega,
            "ubicacion_origen": bodega,
            "ubicacion_destino": zona_bultos,
            "usuario": jefe_bodega,
            **cambios,
        }
        return registrar_embultaje(**datos)

    return hacer
