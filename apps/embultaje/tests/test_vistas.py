"""Pantallas de embultaje y sus permisos (RF-30, RN-23, RN-26, RF-02, RN-05, RN-06)."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.embultaje.models import DocumentoEmbultaje, EmbultajeRegistro
from apps.embultaje.servicios import cerrar_lote
from apps.inventario.servicios import existencia_de


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def url_crear(en_bodega, bodega):
    return reverse("embultaje:registro_crear", args=[en_bodega.pk, bodega.pk])


def _por_bultos(destino, cantidad="3", peso="25"):
    return {
        "ubicacion_destino": destino.pk,
        "usa_calculo_bultos": "on",
        "cantidad_bultos": cantidad,
        "peso_por_bulto": peso,
    }


# --- Registrar ---------------------------------------------------------------


def test_el_formulario_propone_la_zona_de_bultos(cliente, url_crear, zona_bultos):
    form = cliente.get(url_crear).context["form"]
    assert form.fields["ubicacion_destino"].initial == zona_bultos


def test_registrar_por_bultos_lleva_al_documento_del_dia(
    cliente, url_crear, en_bodega, bodega, zona_bultos
):
    respuesta = cliente.post(url_crear, _por_bultos(zona_bultos), follow=True)

    documento = DocumentoEmbultaje.objects.get()
    assert respuesta.redirect_chain[-1][0] == reverse(
        "embultaje:documento_detalle", args=[documento.pk]
    )
    assert "Se embultaron 75.00 kg del lote L-000001 en 3 bultos" in respuesta.content.decode()
    assert existencia_de(en_bodega, bodega) == Decimal("25")


def test_registrar_con_total_digitado(cliente, url_crear, zona_bultos):
    cliente.post(url_crear, {"ubicacion_destino": zona_bultos.pk, "total_kilos": "40"})
    registro = EmbultajeRegistro.objects.get()
    assert registro.total_kilos == Decimal("40")
    assert not registro.bultos.exists()


def test_por_bultos_exige_cantidad_y_peso(cliente, url_crear, zona_bultos):
    datos = _por_bultos(zona_bultos, cantidad="", peso="")
    respuesta = cliente.post(url_crear, datos)
    errores = respuesta.context["form"].errors
    assert "cantidad_bultos" in errores
    assert "peso_por_bulto" in errores
    assert not EmbultajeRegistro.objects.exists()


def test_un_error_de_negocio_se_muestra_en_el_formulario(cliente, url_crear, zona_bultos):
    respuesta = cliente.post(url_crear, _por_bultos(zona_bultos, cantidad="5"))  # 125 > 100
    assert respuesta.status_code == 200
    assert "No hay existencia suficiente" in respuesta.content.decode()


def test_el_detalle_del_registro_lista_sus_bultos(cliente, url_crear, zona_bultos):
    cliente.post(url_crear, _por_bultos(zona_bultos))
    registro = EmbultajeRegistro.objects.get()
    url = reverse("embultaje:registro_detalle", args=[registro.pk])
    contenido = cliente.get(url).content.decode()
    for bulto in registro.bultos.all():
        assert bulto.consecutivo in contenido


def test_consulta_ve_la_lista_y_el_documento(client, consulta, embultar):
    registro = embultar(total_kilos="10")
    client.force_login(consulta)
    assert client.get(reverse("embultaje:documento_lista")).status_code == 200
    url = reverse("embultaje:documento_detalle", args=[registro.documento_embultaje_id])
    assert "L-000001" in client.get(url).content.decode()


# --- Botones en el inventario ------------------------------------------------


def test_el_inventario_ofrece_embultar_salvo_desde_la_zona_de_bultos(
    cliente, embultar, en_bodega, bodega, zona_bultos
):
    embultar(total_kilos="10")
    contenido = cliente.get(reverse("inventario:existencias")).content.decode()
    assert reverse("embultaje:registro_crear", args=[en_bodega.pk, bodega.pk]) in contenido
    assert reverse("embultaje:registro_crear", args=[en_bodega.pk, zona_bultos.pk]) not in contenido


def test_el_historial_ofrece_cerrar_el_lote_cuando_ya_se_embulto(cliente, embultar, en_bodega):
    url_lote = reverse("inventario:lote_detalle", args=[en_bodega.pk])
    url_cierre = reverse("embultaje:lote_cerrar", args=[en_bodega.pk])
    assert url_cierre not in cliente.get(url_lote).content.decode()
    embultar(total_kilos="10")
    assert url_cierre in cliente.get(url_lote).content.decode()


# --- Cerrar el lote ----------------------------------------------------------


def test_la_vista_previa_muestra_la_merma_y_cerrar_la_registra(cliente, embultar, en_bodega):
    embultar(total_kilos="90")
    url = reverse("embultaje:lote_cerrar", args=[en_bodega.pk])
    assert "10,00 kg" in cliente.get(url).content.decode()  # merma que se registrará

    respuesta = cliente.post(url, follow=True)

    en_bodega.refresh_from_db()
    assert en_bodega.estado == "EMBULTADO"
    url_lote = reverse("inventario:lote_detalle", args=[en_bodega.pk])
    assert respuesta.redirect_chain[-1][0] == url_lote
    contenido = respuesta.content.decode()
    assert "90.00 kg embultados y 10.00 kg de merma" in contenido
    assert "Merma de embultaje" in contenido


def test_la_vista_previa_avisa_si_no_se_puede_cerrar(cliente, en_bodega):
    url = reverse("embultaje:lote_cerrar", args=[en_bodega.pk])
    contenido = cliente.get(url).content.decode()
    assert "no tiene embultajes registrados" in contenido
    assert "Cerrar lote</button>" not in contenido
    cliente.post(url)
    en_bodega.refresh_from_db()
    assert en_bodega.estado == "DISPONIBLE"


def test_un_lote_ya_cerrado_vuelve_a_su_historial(cliente, embultar, en_bodega, jefe_bodega):
    embultar(total_kilos="90")
    cerrar_lote(lote=en_bodega, usuario=jefe_bodega)
    respuesta = cliente.get(reverse("embultaje:lote_cerrar", args=[en_bodega.pk]), follow=True)
    assert "ya está cerrado como embultado" in respuesta.content.decode()


# --- Permisos ----------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_sin_perfil_de_bodega_no_se_embulta_ni_se_cierra(
    request, client, perfil, url_crear, en_bodega, zona_bultos
):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(url_crear).status_code == 403
    assert client.post(url_crear, _por_bultos(zona_bultos)).status_code == 403
    cierre = reverse("embultaje:lote_cerrar", args=[en_bodega.pk])
    assert client.post(cierre).status_code == 403
    assert not EmbultajeRegistro.objects.exists()


def test_el_administrador_de_pdv_no_ve_el_embultaje(client, admin_pdv, embultar):
    """RN-06: es un proceso de bodega."""
    registro = embultar(total_kilos="10")
    client.force_login(admin_pdv)
    assert client.get(reverse("embultaje:documento_lista")).status_code == 403
    url = reverse("embultaje:documento_detalle", args=[registro.documento_embultaje_id])
    assert client.get(url).status_code == 403
    menu = client.get(reverse("inicio")).content.decode()
    assert reverse("embultaje:documento_lista") not in menu


def test_el_menu_ofrece_embultaje_al_jefe_de_bodega(cliente):
    contenido = cliente.get(reverse("inicio")).content.decode()
    assert reverse("embultaje:documento_lista") in contenido


def test_la_lista_va_del_documento_mas_reciente_al_mas_antiguo(cliente, jefe_bodega):
    """Con conteos agregados el orden del modelo se pierde: la vista lo fija."""
    for dia in (3, 1, 2):
        DocumentoEmbultaje.objects.create(fecha=date(2026, 10, dia), usuario=jefe_bodega)
    pagina = cliente.get(reverse("embultaje:documento_lista")).context["pagina"]
    assert [d.fecha.day for d in pagina] == [3, 2, 1]
