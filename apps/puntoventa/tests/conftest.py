import pytest

from apps.maestros.models import CategoriaProducto, Cliente, Producto
from apps.puntoventa.servicios import registrar_movimiento_pdv


@pytest.fixture
def con_stock(punto_venta, producto, gerente):
    """30 kg de pechuga en la vitrina del punto, como tras aceptar un traslado."""
    registrar_movimiento_pdv(
        ubicacion=punto_venta,
        producto=producto,
        tipo="ENTRADA_TRASLADO",
        cantidad="30",
        usuario=gerente,
    )
    return producto


@pytest.fixture
def tilapia(punto_venta, gerente, producto):
    """Un segundo producto con 10 kg en el punto."""
    otro = Producto.objects.create(
        codigo="PES-001",
        nombre="Tilapia",
        unidad_medida="KG",
        categoria=CategoriaProducto.objects.get_or_create(nombre="Pescado")[0],
    )
    registrar_movimiento_pdv(
        ubicacion=punto_venta,
        producto=otro,
        tipo="ENTRADA_TRASLADO",
        cantidad="10",
        usuario=gerente,
    )
    return otro


@pytest.fixture
def restaurante(db):
    """Restaurante que ya autorizó el tratamiento de sus datos (Ley 1581)."""
    return Cliente.objects.create(
        tipo_documento="NIT",
        numero_documento="900777111",
        razon_social="Restaurante La Ribera",
        autoriza_tratamiento_datos=True,
        fecha_autorizacion="2026-10-01",
    )


@pytest.fixture
def restaurante_sin_autorizar(db):
    return Cliente.objects.create(
        tipo_documento="NIT", numero_documento="900888222", razon_social="Asadero El Fogón"
    )


def linea(producto, cantidad):
    return {"producto": producto, "cantidad": cantidad}
