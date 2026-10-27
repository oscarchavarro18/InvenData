"""Pantallas del despacho mayorista y sus permisos (RF-35 a RF-37, RF-02, RN-06)."""

import json
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.auditoria.models import Evidencia
from apps.despacho.models import DespachoMayorista
from apps.embultaje.models import AlistamientoDetalle
from apps.inventario.servicios import existencia_de


@pytest.fixture
def cliente_web(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _datos(pedido, cantidad=None, numero="R-0001"):
    """POST como lo arma el navegador: encabezado y una fila por lote alistado."""
    detalles = AlistamientoDetalle.objects.filter(pedido_linea__pedido=pedido).order_by("pk")
    datos = {
        "placa_vehiculo": "XYZ987",
        "nombre_conductor": "Carlos Pérez",
        "numero_sello": "",
        "tipo_documento": "REMISION",
        "numero_documento": numero,
        "valor_total": "",
        "form-TOTAL_FORMS": str(len(detalles)),
        "form-INITIAL_FORMS": str(len(detalles)),
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
    }
    for i, detalle in enumerate(detalles):
        datos[f"form-{i}-alistamiento"] = detalle.pk
        datos[f"form-{i}-cantidad"] = cantidad or detalle.cantidad
        datos[f"form-{i}-cantidad_bultos_cajas"] = "3"
    return datos


def _url_crear(pedido):
    return reverse("despacho:despacho_crear", args=[pedido.pk])


# --- Despachar ---------------------------------------------------------------


def test_la_lista_ofrece_despachar_los_pedidos_alistados(cliente_web, alistado):
    contenido = cliente_web.get(reverse("despacho:despacho_lista")).content.decode()
    assert alistado.consecutivo in contenido
    assert _url_crear(alistado) in contenido


def test_el_pedido_alistado_enlaza_al_despacho(cliente_web, alistado):
    url = reverse("embultaje:pedido_detalle", args=[alistado.pk])
    assert _url_crear(alistado) in cliente_web.get(url).content.decode()


def test_el_formulario_propone_lo_alistado(cliente_web, alistado):
    formset = cliente_web.get(_url_crear(alistado)).context["formset"]
    assert [f.initial["cantidad"] for f in formset] == [Decimal("60")]


def test_despachar_desde_la_pantalla(cliente_web, alistado, en_bultos, zona_bultos):
    respuesta = cliente_web.post(_url_crear(alistado), _datos(alistado), follow=True)

    despacho = DespachoMayorista.objects.get()
    url = reverse("despacho:despacho_detalle", args=[despacho.pk])
    assert respuesta.redirect_chain[-1][0] == url
    contenido = respuesta.content.decode()
    assert "la existencia ya se descontó" in contenido
    assert "Remisión R-0001" in contenido
    assert existencia_de(en_bultos, zona_bultos) == Decimal("40")


def test_un_error_de_negocio_se_muestra_en_el_formulario(cliente_web, alistado):
    respuesta = cliente_web.post(_url_crear(alistado), _datos(alistado, cantidad="150"))
    assert respuesta.status_code == 200
    assert "No hay existencia suficiente" in respuesta.content.decode()
    assert not DespachoMayorista.objects.exists()


def test_un_pedido_sin_alistar_no_se_despacha(cliente_web, alistado):
    cliente_web.post(_url_crear(alistado), _datos(alistado))
    respuesta = cliente_web.get(_url_crear(alistado), follow=True)
    assert "no está alistado para despacho" in respuesta.content.decode()


# --- Entrega -----------------------------------------------------------------


@pytest.fixture
def despacho(cliente_web, alistado):
    cliente_web.post(_url_crear(alistado), _datos(alistado))
    return DespachoMayorista.objects.get()


def test_registrar_la_firma_en_pantalla(cliente_web, despacho):
    url = reverse("despacho:entrega_registrar", args=[despacho.pk])
    firma = [[[100, 500], [300, 450]]]
    respuesta = cliente_web.post(
        url, {"nombre_recibe": "Ana Ruiz", "firma": json.dumps(firma)}, follow=True
    )
    contenido = respuesta.content.decode()
    assert "Constancia de entrega registrada" in contenido
    assert 'd="M100,500 L300,450"' in contenido  # la firma se dibuja de nuevo en SVG


def test_sin_firma_ni_foto_muestra_el_error(cliente_web, despacho):
    url = reverse("despacho:entrega_registrar", args=[despacho.pk])
    respuesta = cliente_web.post(url, {"nombre_recibe": "Ana Ruiz", "firma": ""}, follow=True)
    assert "Capture la firma en pantalla" in respuesta.content.decode()
    despacho.refresh_from_db()
    assert despacho.fecha_hora_recepcion is None


def test_la_foto_solo_la_ven_quienes_ven_la_bodega(
    client, cliente_web, despacho, media, consulta, admin_pdv
):
    url = reverse("despacho:entrega_registrar", args=[despacho.pk])
    foto = SimpleUploadedFile("firmado.png", b"PNGDATA", content_type="image/png")
    cliente_web.post(url, {"nombre_recibe": "Ana Ruiz", "firma": "", "archivo": foto})
    evidencia = Evidencia.objects.get()
    ver = reverse("despacho:evidencia_ver", args=[despacho.pk, evidencia.pk])
    detalle = reverse("despacho:despacho_detalle", args=[despacho.pk])
    assert ver in cliente_web.get(detalle).content.decode()

    client.force_login(consulta)
    respuesta = client.get(ver)
    assert respuesta.status_code == 200
    assert b"".join(respuesta.streaming_content) == b"PNGDATA"

    client.force_login(admin_pdv)
    assert client.get(ver).status_code == 403


def test_una_evidencia_de_otro_documento_no_se_muestra(cliente_web, despacho, gerente, media):
    otra = Evidencia.objects.create(
        entidad="documento_proveedor",
        registro_id=despacho.pk,
        archivo=SimpleUploadedFile("otra.png", b"X", content_type="image/png"),
        usuario=gerente,
    )
    url = reverse("despacho:evidencia_ver", args=[despacho.pk, otra.pk])
    assert cliente_web.get(url).status_code == 404


# --- Permisos ----------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_sin_perfil_de_bodega_no_se_despacha(request, client, perfil, alistado):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(_url_crear(alistado)).status_code == 403
    assert client.post(_url_crear(alistado), _datos(alistado)).status_code == 403
    assert not DespachoMayorista.objects.exists()


def test_consulta_ve_el_despacho_sin_formulario_de_entrega(client, consulta, despacho):
    client.force_login(consulta)
    url = reverse("despacho:despacho_detalle", args=[despacho.pk])
    contenido = client.get(url).content.decode()
    assert "R-0001" in contenido
    assert "Registrar entrega" not in contenido


def test_el_administrador_de_pdv_no_ve_los_despachos(client, admin_pdv, despacho):
    """RN-06: el despacho es de bodega."""
    client.force_login(admin_pdv)
    assert client.get(reverse("despacho:despacho_lista")).status_code == 403
    url = reverse("despacho:despacho_detalle", args=[despacho.pk])
    assert client.get(url).status_code == 403


def test_el_menu_ofrece_despachos_al_jefe_de_bodega(cliente_web):
    contenido = cliente_web.get(reverse("inicio")).content.decode()
    assert reverse("despacho:despacho_lista") in contenido
