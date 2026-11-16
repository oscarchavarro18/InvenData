import pytest

from apps.inventario.servicios import registrar_movimiento
from apps.puntoventa.servicios import registrar_movimiento_pdv


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    """El lote con 30 kg en el cuarto de sostenimiento."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="30", usuario=gerente, ubicacion_destino=bodega
    )
    return lote


@pytest.fixture
def en_punto(punto_venta, producto, gerente):
    """20 kg del producto en la vitrina del punto de venta."""
    registrar_movimiento_pdv(
        ubicacion=punto_venta,
        producto=producto,
        tipo="ENTRADA_TRASLADO",
        cantidad="20",
        usuario=gerente,
    )
    return producto
