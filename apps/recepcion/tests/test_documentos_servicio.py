from datetime import date
from decimal import Decimal

import pytest

from apps.maestros.models import Producto
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea
from apps.recepcion.servicios import (
    RecepcionInvalida,
    agregar_linea,
    crear_documento,
    eliminar_linea,
)


@pytest.fixture
def proveedor(linea):
    return linea.documento_proveedor.proveedor


@pytest.fixture
def datos_documento(proveedor):
    return {
        "proveedor": proveedor,
        "tipo_documento": "REMISION",
        "numero_documento": "R-500",
        "fecha": date(2026, 10, 19),
    }


@pytest.fixture
def documento(datos_documento):
    return crear_documento(**datos_documento)


@pytest.fixture
def tilapia(producto):
    return Producto.objects.create(
        codigo="PES-001", nombre="Tilapia", unidad_medida="KG", categoria=producto.categoria
    )


# --- crear_documento ------------------------------------------------------------


def test_crear_documento_lo_deja_abierto_y_sin_lineas(datos_documento):
    documento = crear_documento(**datos_documento)
    assert documento.estado == "ABIERTO"
    assert documento.numero_documento == "R-500"
    assert documento.lineas.count() == 0


def test_el_numero_del_documento_se_limpia_de_espacios(datos_documento):
    datos_documento["numero_documento"] = "  R-500  "
    assert crear_documento(**datos_documento).numero_documento == "R-500"


def test_no_se_repite_el_mismo_documento_del_mismo_proveedor(datos_documento, documento):
    with pytest.raises(RecepcionInvalida, match="Ya existe"):
        crear_documento(**datos_documento)
    assert DocumentoProveedor.objects.filter(numero_documento="R-500").count() == 1


def test_el_mismo_numero_se_permite_con_otro_tipo(datos_documento, documento):
    datos_documento["tipo_documento"] = "FACTURA"
    assert crear_documento(**datos_documento).tipo_documento == "FACTURA"


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("tipo_documento", "RECIBO"),
        ("numero_documento", ""),
        ("numero_documento", "   "),
        ("numero_documento", None),
        ("numero_documento", "X" * 31),
        ("fecha", "2026-10-19"),
        ("fecha", None),
    ],
)
def test_documento_con_datos_invalidos_se_rechaza(datos_documento, campo, valor):
    datos_documento[campo] = valor
    with pytest.raises(RecepcionInvalida):
        crear_documento(**datos_documento)


def test_no_se_crea_un_documento_de_un_proveedor_inactivo(datos_documento, proveedor):
    proveedor.activo = False
    proveedor.save()
    with pytest.raises(RecepcionInvalida, match="inactivo"):
        crear_documento(**datos_documento)


# --- agregar_linea --------------------------------------------------------------


def test_agregar_linea(documento, producto):
    linea = agregar_linea(documento=documento, producto=producto, cantidad=Decimal("80.50"))
    assert linea.documento_proveedor == documento
    assert linea.cantidad == Decimal("80.50")
    assert linea.cantidad_recibida is None


def test_agregar_linea_acepta_texto(documento, producto):
    linea = agregar_linea(documento=documento, producto=producto, cantidad="12.5")
    assert linea.cantidad == Decimal("12.50")


def test_un_documento_admite_varios_productos(documento, producto, tilapia):
    agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))
    agregar_linea(documento=documento, producto=tilapia, cantidad=Decimal("20"))
    assert documento.lineas.count() == 2


def test_no_se_repite_un_producto_en_el_mismo_documento(documento, producto):
    agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))
    with pytest.raises(RecepcionInvalida, match="ya está en el documento"):
        agregar_linea(documento=documento, producto=producto, cantidad=Decimal("5"))
    assert documento.lineas.count() == 1


@pytest.mark.parametrize(
    "cantidad",
    [Decimal("0"), Decimal("-3"), "abc", Decimal("1.234"), Decimal("NaN"), Decimal("100000000")],
)
def test_linea_con_cantidad_invalida_se_rechaza(documento, producto, cantidad):
    with pytest.raises(RecepcionInvalida):
        agregar_linea(documento=documento, producto=producto, cantidad=cantidad)
    assert documento.lineas.count() == 0


def test_no_se_agrega_un_producto_inactivo(documento, producto):
    producto.activo = False
    producto.save()
    with pytest.raises(RecepcionInvalida, match="inactivo"):
        agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))


def test_no_se_agregan_lineas_a_un_documento_cerrado(documento, producto):
    documento.estado = "CERRADO"
    documento.save()
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))


# --- eliminar_linea -------------------------------------------------------------


def test_eliminar_una_linea(documento, producto):
    linea = agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))
    eliminar_linea(linea=linea)
    assert documento.lineas.count() == 0


def test_no_se_elimina_una_linea_con_lotes(lote, linea):
    with pytest.raises(RecepcionInvalida, match="ya tiene lotes"):
        eliminar_linea(linea=linea)
    assert DocumentoProveedorLinea.objects.filter(pk=linea.pk).exists()


def test_no_se_elimina_una_linea_de_un_documento_cerrado(documento, producto):
    linea = agregar_linea(documento=documento, producto=producto, cantidad=Decimal("10"))
    documento.estado = "CERRADO"
    documento.save()
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        eliminar_linea(linea=linea)
