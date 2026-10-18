from datetime import date
from decimal import Decimal

import pytest

from apps.inventario.models import Lote
from apps.maestros.models import CategoriaProducto, Producto, Proveedor, Ubicacion
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea


@pytest.fixture
def producto(db):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    return Producto.objects.create(
        codigo="POL-001", nombre="Pechuga", unidad_medida="KG", categoria=categoria
    )


@pytest.fixture
def linea(producto):
    proveedor = Proveedor.objects.create(
        tipo_documento="NIT", numero_documento="900123456", razon_social="Avícola del Huila"
    )
    documento = DocumentoProveedor.objects.create(
        proveedor=proveedor,
        tipo_documento="FACTURA",
        numero_documento="F-100",
        fecha=date(2026, 10, 1),
    )
    return DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("100")
    )


@pytest.fixture
def datos_lote(producto):
    """Campos comunes que todo lote necesita, sin importar su origen."""
    return {
        "producto": producto,
        "estado_producto": "FRESCO",
        "fecha_vencimiento": date(2026, 12, 1),
    }


@pytest.fixture
def lote(linea, datos_lote):
    """Lote de recepción: el caso normal."""
    return Lote.objects.create(
        codigo="L-000001", origen="RECEPCION", documento_proveedor_linea=linea, **datos_lote
    )


@pytest.fixture
def tunel(db):
    return Ubicacion.objects.create(
        codigo="TUN-01", nombre="Túnel de congelación 1", tipo="TUNEL_CONGELACION"
    )
