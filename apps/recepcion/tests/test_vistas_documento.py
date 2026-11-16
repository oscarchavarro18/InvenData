from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def proveedor(linea):
    return linea.documento_proveedor.proveedor


@pytest.fixture
def datos(proveedor):
    return {
        "proveedor": proveedor.pk,
        "tipo_documento": "REMISION",
        "numero_documento": "R-500",
        "fecha": "2026-10-19",
    }


def mensajes(respuesta):
    return [str(m) for m in respuesta.context["messages"]]


# --- Crear documento --------------------------------------------------------------


def test_el_formulario_de_documento_se_muestra(cliente):
    respuesta = cliente.get(reverse("recepcion:documento_crear"))
    assert respuesta.status_code == 200
    assert "Nuevo documento del proveedor" in respuesta.content.decode()


def test_crear_documento_lleva_a_su_detalle(cliente, datos):
    respuesta = cliente.post(reverse("recepcion:documento_crear"), datos, follow=True)
    documento = DocumentoProveedor.objects.get(numero_documento="R-500")
    assert respuesta.redirect_chain == [
        (reverse("recepcion:documento_detalle", args=[documento.pk]), 302)
    ]
    assert documento.fecha == date(2026, 10, 19)
    assert "Documento creado" in mensajes(respuesta)[0]


def test_crear_documento_repetido_muestra_el_error(cliente, datos):
    cliente.post(reverse("recepcion:documento_crear"), datos)
    respuesta = cliente.post(reverse("recepcion:documento_crear"), datos)
    assert respuesta.status_code == 200
    assert "Ya existe el documento" in respuesta.content.decode()
    assert DocumentoProveedor.objects.filter(numero_documento="R-500").count() == 1


def test_crear_documento_con_datos_incompletos_muestra_los_errores(cliente, datos):
    datos["numero_documento"] = ""
    respuesta = cliente.post(reverse("recepcion:documento_crear"), datos)
    assert respuesta.status_code == 200
    assert respuesta.context["form"].errors
    assert not DocumentoProveedor.objects.filter(numero_documento="").exists()


def test_crear_documento_exige_iniciar_sesion(client, datos):
    respuesta = client.post(reverse("recepcion:documento_crear"), datos)
    assert respuesta.status_code == 302
    assert respuesta.url.startswith(reverse("login"))
    assert not DocumentoProveedor.objects.filter(numero_documento="R-500").exists()


# --- Agregar línea ----------------------------------------------------------------


def test_agregar_linea_desde_la_pantalla(cliente, linea, producto):
    otro = DocumentoProveedor.objects.create(
        proveedor=linea.documento_proveedor.proveedor,
        tipo_documento="REMISION",
        numero_documento="R-1",
        fecha=date(2026, 10, 19),
    )
    url = reverse("recepcion:linea_agregar", args=[otro.pk])
    respuesta = cliente.post(url, {"producto": producto.pk, "cantidad": "80.50"}, follow=True)
    nueva = DocumentoProveedorLinea.objects.get(documento_proveedor=otro)
    assert nueva.cantidad == Decimal("80.50")
    assert mensajes(respuesta) == ["Línea agregada."]


def test_agregar_producto_repetido_avisa_sin_romper(cliente, linea, producto):
    url = reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id])
    respuesta = cliente.post(url, {"producto": producto.pk, "cantidad": "5"}, follow=True)
    assert respuesta.status_code == 200
    assert "ya está en el documento" in mensajes(respuesta)[0]
    assert linea.documento_proveedor.lineas.count() == 1


def test_agregar_linea_con_cantidad_invalida_avisa(cliente, linea, producto):
    url = reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id])
    respuesta = cliente.post(url, {"producto": producto.pk, "cantidad": "-4"}, follow=True)
    assert len(mensajes(respuesta)) == 1
    assert "Cantidad" in mensajes(respuesta)[0]


def test_agregar_linea_a_un_documento_cerrado_avisa(cliente, linea, producto):
    documento = linea.documento_proveedor
    documento.estado = "CERRADO"
    documento.save()
    url = reverse("recepcion:linea_agregar", args=[documento.pk])
    respuesta = cliente.post(url, {"producto": producto.pk, "cantidad": "5"}, follow=True)
    assert "cerrado" in mensajes(respuesta)[0]


def test_agregar_linea_solo_acepta_post(cliente, linea):
    url = reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id])
    assert cliente.get(url).status_code == 405


def test_agregar_linea_exige_iniciar_sesion(client, linea, producto):
    url = reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id])
    assert client.post(url, {"producto": producto.pk, "cantidad": "5"}).status_code == 302


# --- Quitar línea -----------------------------------------------------------------


def test_quitar_una_linea(cliente, linea):
    url = reverse("recepcion:linea_eliminar", args=[linea.pk])
    respuesta = cliente.post(url, follow=True)
    assert not DocumentoProveedorLinea.objects.filter(pk=linea.pk).exists()
    assert mensajes(respuesta) == ["Línea eliminada."]


def test_quitar_una_linea_con_lotes_avisa(cliente, linea, lote):
    url = reverse("recepcion:linea_eliminar", args=[linea.pk])
    respuesta = cliente.post(url, follow=True)
    assert DocumentoProveedorLinea.objects.filter(pk=linea.pk).exists()
    assert "ya tiene lotes" in mensajes(respuesta)[0]


def test_quitar_linea_solo_acepta_post(cliente, linea):
    assert cliente.get(reverse("recepcion:linea_eliminar", args=[linea.pk])).status_code == 405


# --- El detalle ofrece las acciones solo con el documento abierto -----------------


def test_el_detalle_abierto_ofrece_agregar_y_quitar(cliente, linea):
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    contenido = cliente.get(url).content.decode()
    assert "Agregar producto al documento" in contenido
    assert "Quitar" in contenido


def test_el_detalle_cerrado_no_ofrece_cambios(cliente, linea):
    documento = linea.documento_proveedor
    documento.estado = "CERRADO"
    documento.save()
    contenido = cliente.get(
        reverse("recepcion:documento_detalle", args=[documento.pk])
    ).content.decode()
    assert "Agregar producto al documento" not in contenido
    assert "Quitar" not in contenido


def test_enviar_el_formulario_vacio_muestra_los_errores(cliente):
    respuesta = cliente.post(reverse("recepcion:documento_crear"), {})
    assert respuesta.status_code == 200
    assert {"proveedor", "tipo_documento", "numero_documento", "fecha"} <= set(
        respuesta.context["form"].errors
    )
