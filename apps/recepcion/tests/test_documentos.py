from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.maestros.models import CategoriaProducto, Producto, Proveedor
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea


@pytest.fixture
def proveedor(db):
    return Proveedor.objects.create(
        tipo_documento="NIT", numero_documento="900123456", razon_social="Avícola del Huila"
    )


@pytest.fixture
def otro_proveedor(db):
    return Proveedor.objects.create(
        tipo_documento="NIT", numero_documento="800765432", razon_social="Pesquera del Sur"
    )


@pytest.fixture
def producto(db):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    return Producto.objects.create(
        codigo="POL-001", nombre="Pechuga", unidad_medida="KG", categoria=categoria
    )


@pytest.fixture
def documento(proveedor):
    return DocumentoProveedor.objects.create(
        proveedor=proveedor,
        tipo_documento="FACTURA",
        numero_documento="F-100",
        fecha=date(2026, 10, 1),
    )


# --- Documento del proveedor -------------------------------------------------


def test_documento_nace_abierto(documento):
    assert documento.estado == "ABIERTO"


def test_documento_se_muestra_con_tipo_y_numero(documento):
    assert str(documento) == "FACTURA F-100"


def test_numero_repetido_del_mismo_proveedor_se_rechaza(documento, proveedor):
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoProveedor.objects.create(
            proveedor=proveedor,
            tipo_documento="FACTURA",
            numero_documento="F-100",
            fecha=date(2026, 10, 2),
        )


def test_mismo_numero_con_otro_tipo_es_valido(documento, proveedor):
    DocumentoProveedor.objects.create(
        proveedor=proveedor,
        tipo_documento="REMISION",
        numero_documento="F-100",
        fecha=date(2026, 10, 1),
    )
    assert DocumentoProveedor.objects.count() == 2


def test_mismo_numero_en_otro_proveedor_es_valido(documento, otro_proveedor):
    DocumentoProveedor.objects.create(
        proveedor=otro_proveedor,
        tipo_documento="FACTURA",
        numero_documento="F-100",
        fecha=date(2026, 10, 1),
    )
    assert DocumentoProveedor.objects.count() == 2


def test_tipo_de_documento_invalido_se_rechaza(proveedor):
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoProveedor.objects.create(
            proveedor=proveedor,
            tipo_documento="ORDEN",
            numero_documento="X-1",
            fecha=date(2026, 10, 1),
        )


def test_estado_invalido_se_rechaza(proveedor):
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoProveedor.objects.create(
            proveedor=proveedor,
            tipo_documento="FACTURA",
            numero_documento="X-2",
            fecha=date(2026, 10, 1),
            estado="ANULADO",
        )


def test_los_documentos_se_listan_del_mas_reciente_al_mas_antiguo(documento, proveedor):
    viejo = DocumentoProveedor.objects.create(
        proveedor=proveedor,
        tipo_documento="FACTURA",
        numero_documento="F-050",
        fecha=date(2026, 9, 15),
    )
    assert list(DocumentoProveedor.objects.all()) == [documento, viejo]


# --- Líneas del documento ----------------------------------------------------


def test_linea_nace_sin_cantidad_recibida_ni_diferencia(documento, producto):
    linea = DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("120.50")
    )
    linea.refresh_from_db()
    assert linea.cantidad == Decimal("120.50")
    assert linea.cantidad_recibida is None
    assert linea.diferencia_kg is None


@pytest.mark.parametrize("cantidad", [Decimal("0"), Decimal("-5.00")])
def test_linea_rechaza_cantidad_que_no_es_positiva(documento, producto, cantidad):
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoProveedorLinea.objects.create(
            documento_proveedor=documento, producto=producto, cantidad=cantidad
        )


def test_linea_acepta_la_cantidad_positiva_minima(documento, producto):
    linea = DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("0.01")
    )
    assert linea.pk is not None


def test_un_documento_agrupa_varias_lineas(documento, producto):
    otro = Producto.objects.create(
        codigo="POL-002", nombre="Muslo", unidad_medida="KG", categoria=producto.categoria
    )
    DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("100")
    )
    DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=otro, cantidad=Decimal("60")
    )
    assert documento.lineas.count() == 2


# --- Protección de datos relacionados ---------------------------------------


def test_no_se_borra_un_proveedor_con_documentos(documento, proveedor):
    with pytest.raises(ProtectedError):
        proveedor.delete()


def test_no_se_borra_un_documento_con_lineas(documento, producto):
    DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("10")
    )
    with pytest.raises(ProtectedError):
        documento.delete()


def test_no_se_borra_un_producto_con_lineas_de_recepcion(documento, producto):
    DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=Decimal("10")
    )
    with pytest.raises(ProtectedError):
        producto.delete()
