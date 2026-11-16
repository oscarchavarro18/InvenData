from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.maestros.forms import ParametroForm
from apps.maestros.models import (
    CategoriaProducto,
    Cliente,
    Parametro,
    Producto,
    Proveedor,
    TipoEmbalaje,
)


@pytest.fixture
def categoria(db):
    return CategoriaProducto.objects.create(nombre="Pollo")


@pytest.fixture
def producto(categoria):
    return Producto.objects.create(
        codigo="POL-001", nombre="Pechuga", unidad_medida="KG", categoria=categoria
    )


def test_producto_codigo_es_unico(producto, categoria):
    with pytest.raises(IntegrityError), transaction.atomic():
        Producto.objects.create(
            codigo="POL-001", nombre="Otro", unidad_medida="KG", categoria=categoria
        )


def test_producto_rechaza_unidad_de_medida_invalida(categoria):
    with pytest.raises(IntegrityError), transaction.atomic():
        Producto.objects.create(
            codigo="X-1", nombre="Raro", unidad_medida="TONELADA", categoria=categoria
        )


def test_producto_nace_sin_transformacion_y_activo(producto):
    assert producto.admite_transformacion is False
    assert producto.activo is True


def test_no_se_puede_borrar_una_categoria_con_productos(producto, categoria):
    with pytest.raises(ProtectedError):
        categoria.delete()


def test_nombre_de_categoria_es_unico(categoria):
    with pytest.raises(IntegrityError), transaction.atomic():
        CategoriaProducto.objects.create(nombre="Pollo")


@pytest.mark.parametrize("modelo", [Proveedor, Cliente])
def test_documento_unico_por_tipo_y_numero(db, modelo):
    modelo.objects.create(tipo_documento="NIT", numero_documento="900123", razon_social="A")
    with pytest.raises(IntegrityError), transaction.atomic():
        modelo.objects.create(tipo_documento="NIT", numero_documento="900123", razon_social="B")
    # El mismo número con otro tipo de documento sí es una persona distinta.
    modelo.objects.create(tipo_documento="CC", numero_documento="900123", razon_social="C")


def test_proveedor_acepta_pasaporte_y_cliente_no(db):
    Proveedor.objects.create(tipo_documento="PAS", numero_documento="P1", razon_social="Ext")
    with pytest.raises(IntegrityError), transaction.atomic():
        Cliente.objects.create(tipo_documento="PAS", numero_documento="P1", razon_social="Ext")


def test_cliente_nace_sin_autorizacion_de_datos(db):
    cliente = Cliente.objects.create(
        tipo_documento="NIT", numero_documento="1", razon_social="Restaurante"
    )
    assert cliente.autoriza_tratamiento_datos is False
    assert cliente.fecha_autorizacion is None


def test_fecha_de_autorizacion_exige_autorizacion(db):
    with pytest.raises(IntegrityError), transaction.atomic():
        Cliente.objects.create(
            tipo_documento="NIT",
            numero_documento="2",
            razon_social="Sin permiso",
            fecha_autorizacion=date(2026, 10, 1),
        )
    sin_permiso = Cliente(
        tipo_documento="NIT",
        numero_documento="3",
        razon_social="Sin permiso",
        fecha_autorizacion=date(2026, 10, 1),
    )
    with pytest.raises(ValidationError):
        sin_permiso.full_clean()


def test_cliente_con_autorizacion_y_fecha_es_valido(db):
    cliente = Cliente(
        tipo_documento="NIT",
        numero_documento="4",
        razon_social="Con permiso",
        autoriza_tratamiento_datos=True,
        fecha_autorizacion=date(2026, 10, 1),
    )
    cliente.full_clean()
    cliente.save()


def test_tipo_de_embalaje_permite_tara_cero_y_rechaza_negativa(db):
    TipoEmbalaje.objects.create(nombre="SIN EMBALAJE", peso_tara=Decimal("0.00"))
    with pytest.raises(IntegrityError), transaction.atomic():
        TipoEmbalaje.objects.create(nombre="Absurda", peso_tara=Decimal("-1.00"))


def test_tara_se_guarda_con_dos_decimales(db):
    canastilla = TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("1.85"))
    canastilla.refresh_from_db()
    assert canastilla.peso_tara == Decimal("1.85")


def test_clave_de_parametro_es_unica(db):
    Parametro.objects.create(clave="DIAS_POR_VENCER", valor="7")
    with pytest.raises(IntegrityError), transaction.atomic():
        Parametro.objects.create(clave="DIAS_POR_VENCER", valor="8")


RUTAS_ADMIN = [
    "ubicacion",
    "categoriaproducto",
    "producto",
    "proveedor",
    "cliente",
    "tipoembalaje",
    "parametro",
]


@pytest.mark.parametrize("modelo", RUTAS_ADMIN)
def test_gerente_administra_cada_maestro(client, gerente, modelo):
    client.force_login(gerente)
    assert client.get(f"/admin/maestros/{modelo}/").status_code == 200
    assert client.get(f"/admin/maestros/{modelo}/add/").status_code == 200


@pytest.mark.parametrize("modelo", RUTAS_ADMIN)
def test_otros_perfiles_no_administran_maestros(client, jefe_bodega, modelo):
    client.force_login(jefe_bodega)
    respuesta = client.get(f"/admin/maestros/{modelo}/")
    assert respuesta.status_code == 302
    assert respuesta.url.startswith("/admin/login/")


@pytest.mark.parametrize(
    ("valor", "valido"), [("5", True), ("2,5 %", True), ("abc", False), ("150", False)]
)
def test_el_panel_valida_la_tolerancia_de_balance(db, valor, valido):
    """RF-27: un valor mal escrito bloquearía todas las confirmaciones de transformación."""
    tolerancia = Parametro.objects.get(clave="TOLERANCIA_BALANCE_PCT")
    form = ParametroForm(
        data={"clave": "TOLERANCIA_BALANCE_PCT", "valor": valor}, instance=tolerancia
    )
    assert form.is_valid() is valido


def test_los_demas_parametros_no_se_interpretan(db):
    assert ParametroForm(data={"clave": "NOTA_LIBRE", "valor": "cualquier texto"}).is_valid()
