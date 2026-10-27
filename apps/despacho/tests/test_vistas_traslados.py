"""Pantallas del traslado a PDV y del inventario del punto (RF-38 a RF-45, RF-48, RN-06)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.despacho.models import TrasladoPdv
from apps.maestros.models import Ubicacion
from apps.puntoventa.servicios import existencia_pdv


@pytest.fixture
def enviado(enviar):
    return enviar()


@pytest.fixture
def otro_punto(db):
    return Ubicacion.objects.create(codigo="PDV-02", nombre="Punto de venta 2", tipo="PUNTO_VENTA")


def _detalle(traslado):
    return reverse("despacho:traslado_detalle", args=[traslado.pk])


def _decidir(traslado, accion, peso=None, nombre_coincide=True, observacion=""):
    detalle = traslado.detalles.get()
    datos = {
        "accion": accion,
        f"peso_{detalle.pk}": peso if peso is not None else detalle.cantidad,
        "observacion": observacion,
    }
    if nombre_coincide:
        datos["nombre_coincide"] = "on"
    return datos


# --- Envío desde bodega ------------------------------------------------------


def test_el_formulario_pide_primero_el_origen(client, jefe_bodega, en_bultos):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("despacho:traslado_crear")).content.decode()
    assert "Elija de dónde sale el producto" in contenido


def test_enviar_desde_la_pantalla(client, jefe_bodega, en_bultos, zona_bultos, punto_venta):
    client.force_login(jefe_bodega)
    url = reverse("despacho:traslado_crear") + f"?ubicacion_origen={zona_bultos.pk}"
    assert "L-000001" in client.get(url).content.decode()

    datos = {
        "ubicacion_origen": zona_bultos.pk,
        "ubicacion_destino": punto_venta.pk,
        "nombre_entrega": "Luis Gómez",
        "form-TOTAL_FORMS": "5",
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "form-0-candidato": str(en_bultos.pk),
        "form-0-cantidad": "30",
    }
    respuesta = client.post(reverse("despacho:traslado_crear"), datos, follow=True)

    traslado = TrasladoPdv.objects.get()
    assert respuesta.redirect_chain[-1][0] == _detalle(traslado)
    assert "ya aparece en su bandeja" in respuesta.content.decode()


# --- Bandeja y decisión del PDV ----------------------------------------------


def test_el_pdv_solo_ve_lo_que_le_envian(client, admin_pdv, enviar, otro_punto):
    mio = enviar()
    ajeno = enviar("10", destino=otro_punto)
    client.force_login(admin_pdv)
    pagina = client.get(reverse("despacho:traslado_lista")).context["pagina"]
    assert list(pagina) == [mio]
    assert client.get(_detalle(ajeno)).status_code == 403


def test_el_tablero_del_pdv_muestra_lo_que_tiene_por_recibir(client, admin_pdv, enviado):
    client.force_login(admin_pdv)
    contenido = client.get(reverse("inicio")).content.decode()
    assert "Traslados por recibir" in contenido
    assert _detalle(enviado) in contenido


def test_aceptar_desde_la_pantalla_suma_al_punto(client, admin_pdv, enviado, producto, punto_venta):
    client.force_login(admin_pdv)
    respuesta = client.post(
        reverse("despacho:traslado_decidir", args=[enviado.pk]),
        _decidir(enviado, "aceptar"),
        follow=True,
    )
    assert "el producto ya está en el punto" in respuesta.content.decode()
    assert existencia_pdv(producto, punto_venta) == Decimal("30")
    existencias = client.get(reverse("puntoventa:existencias")).content.decode()
    assert "Pechuga" in existencias


def test_un_peso_distinto_muestra_el_error_y_pide_rechazar(client, admin_pdv, enviado):
    client.force_login(admin_pdv)
    respuesta = client.post(
        reverse("despacho:traslado_decidir", args=[enviado.pk]),
        _decidir(enviado, "aceptar", peso="29.5"),
    )
    assert respuesta.status_code == 200
    assert "rechace el traslado" in respuesta.content.decode()
    enviado.refresh_from_db()
    assert enviado.estado == "ENVIADO"


def test_rechazar_y_bodega_corrige_y_reenvia(client, admin_pdv, jefe_bodega, enviado):
    client.force_login(admin_pdv)
    url = reverse("despacho:traslado_decidir", args=[enviado.pk])
    sin_motivo = client.post(url, _decidir(enviado, "rechazar"))
    assert "motivo del rechazo" in sin_motivo.content.decode()
    client.post(url, _decidir(enviado, "rechazar", observacion="Faltó medio kilo"))
    enviado.refresh_from_db()
    assert enviado.estado == "RECHAZADO"

    client.force_login(jefe_bodega)
    detalle = client.get(_detalle(enviado)).content.decode()
    assert "Faltó medio kilo" in detalle
    reenviar = reverse("despacho:traslado_crear") + f"?anterior={enviado.pk}"
    assert reenviar in detalle
    formulario = client.get(reenviar)
    assert formulario.context["form"].initial["nombre_entrega"] == "Luis Gómez"
    assert [f.initial["cantidad"] for f in formulario.context["formset"].initial_forms] == [
        Decimal("30")
    ]


# --- Permisos ----------------------------------------------------------------


def test_consulta_lee_pero_no_decide_ni_anota(client, consulta, enviado):
    client.force_login(consulta)
    respuesta = client.get(_detalle(enviado))
    assert respuesta.status_code == 200
    assert respuesta.context["verificacion"] is None
    assert respuesta.context["observacion_form"] is None
    assert client.post(reverse("despacho:traslado_crear"), {}).status_code == 403


def test_bodega_no_decide_por_el_pdv(client, jefe_bodega, enviado):
    client.force_login(jefe_bodega)
    url = reverse("despacho:traslado_decidir", args=[enviado.pk])
    assert client.post(url, _decidir(enviado, "aceptar")).status_code == 403


def test_el_pdv_no_crea_traslados(client, admin_pdv):
    client.force_login(admin_pdv)
    assert client.get(reverse("despacho:traslado_crear")).status_code == 403


def test_el_menu_de_cada_perfil(client, admin_pdv, jefe_bodega):
    client.force_login(jefe_bodega)
    bodega = client.get(reverse("inicio")).content.decode()
    assert "Traslados a PDV" in bodega
    assert reverse("puntoventa:existencias") not in bodega  # el jefe no ve los PDV

    client.force_login(admin_pdv)
    punto = client.get(reverse("inicio")).content.decode()
    assert "Traslados recibidos" in punto
    assert reverse("puntoventa:existencias") in punto
    assert f'href="{reverse("despacho:despacho_lista")}"' not in punto


def test_la_existencia_del_pdv_respeta_el_alcance(client, admin_pdv, jefe_bodega, otro_punto):
    """RN-06: el administrador ve solo su punto aunque pida otro; bodega no ve los PDV."""
    client.force_login(admin_pdv)
    respuesta = client.get(reverse("puntoventa:existencias"), {"ubicacion": otro_punto.pk})
    assert respuesta.context["punto"] == admin_pdv.ubicacion
    client.force_login(jefe_bodega)
    assert client.get(reverse("puntoventa:existencias")).status_code == 403
