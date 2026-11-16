from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import CategoriaProducto, Producto, Ubicacion
from apps.transformacion.servicios import crear_orden


@pytest.fixture
def zona(db):
    return Ubicacion.objects.create(
        codigo="TRF-01", nombre="Zona de transformación", tipo="ZONA_TRANSFORMACION"
    )


@pytest.fixture
def transformable(producto):
    """La pechuga del conftest general, marcada como transformable (RF-04, RF-23)."""
    producto.admite_transformacion = True
    producto.save(update_fields=["admite_transformacion"])
    return producto


@pytest.fixture
def porciones(db):
    categoria = CategoriaProducto.objects.create(nombre="Porcionados")
    return Producto.objects.create(
        codigo="POL-002", nombre="Pechuga porcionada", unidad_medida="KG", categoria=categoria
    )


@pytest.fixture
def en_zona(lote, transformable, zona, gerente):
    """El lote con 50 kg en la zona de transformación, listo para cortarse.

    Vence en 60 días contados desde hoy, para que los derivados que heredan su fecha nunca
    queden vencidos frente a la fecha de la orden, sin importar cuándo corran las pruebas.
    """
    lote.fecha_vencimiento = timezone.localdate() + timedelta(days=60)
    lote.save(update_fields=["fecha_vencimiento"])
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="50", usuario=gerente, ubicacion_destino=zona
    )
    lote.refresh_from_db()
    return lote


@pytest.fixture
def orden(en_zona, zona, jefe_bodega):
    """Orden en borrador que consumirá 40 kg de los 50 que hay."""
    return crear_orden(
        lote=en_zona, ubicacion_origen=zona, cantidad_consumida=Decimal("40"), usuario=jefe_bodega
    )


@pytest.fixture
def derivado(porciones, tunel, en_zona):
    """Datos de un derivado tal como llegan del formulario de confirmación."""

    def crear(cantidad, producto=None, destino=None):
        return {
            "producto": producto or porciones,
            "cantidad": Decimal(cantidad),
            "ubicacion_destino": destino or tunel,
            "estado_producto": "CONGELADO",
            "fecha_vencimiento": en_zona.fecha_vencimiento,
        }

    return crear
