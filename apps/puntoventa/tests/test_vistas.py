"""Pantallas de ventas, existencia e historial del PDV y su alcance por perfil
(RF-46 a RF-49, RN-06, RN-07, RNF-01)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.maestros.models import Ubicacion
from apps.puntoventa.models import VentaConsumidorFinal, VentaRestauranteRemision
from apps.puntoventa.servicios import (
    existencia_pdv,
    registrar_movimiento_pdv,
    registrar_venta_consumidor,
)
from apps.puntoventa.tests.conftest import linea


def _nueva(tipo):
    return reverse("puntoventa:venta_nueva", args=[tipo])


def _datos(punto, producto, cantidad="5", **extra):
    return {
        "ubicacion": punto.pk,
        "form-TOTAL_FORMS": "5",
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "form-0-producto": str(producto.pk),
        "form-0-cantidad": cantidad,
        **extra,
    }


@pytest.fixture
def otro_punto(db):
    return Ubicacion.objects.create(codigo="PDV-02", nombre="Punto de venta 2", tipo="PUNTO_VENTA")


# --- Vender ------------------------------------------------------------------


def test_vender_a_consumidor_final_desde_la_pantalla(client, admin_pdv, punto_venta, con_stock):
    client.force_login(admin_pdv)
    formulario = client.get(_nueva("consumidor")).content.decode()
    assert "Pechuga · 30.00 kg disponibles" in formulario

    respuesta = client.post(
        _nueva("consumidor"),
        _datos(punto_venta, con_stock, numero_factura_siigo="FE-77"),
        follow=True,
    )

    venta = VentaConsumidorFinal.objects.get()
    destino = reverse("puntoventa:venta_detalle", args=["consumidor", venta.pk])
    assert respuesta.redirect_chain[-1][0] == destino
    assert "la existencia ya se descontó" in respuesta.content.decode()
    assert existencia_pdv(con_stock, punto_venta) == Decimal("25")


def test_la_remision_pide_la_autorizacion_si_falta(
    client, admin_pdv, punto_venta, con_stock, restaurante_sin_autorizar
):
    client.force_login(admin_pdv)
    formulario = client.get(_nueva("restaurante")).content.decode()
    assert "Asadero El Fogón · NIT 900888222 (sin autorización de datos)" in formulario

    datos = _datos(punto_venta, con_stock, cliente=restaurante_sin_autorizar.pk)
    sin_casilla = client.post(_nueva("restaurante"), datos)
    assert "no ha autorizado el tratamiento de sus datos" in sin_casilla.content.decode()
    assert not VentaRestauranteRemision.objects.exists()

    client.post(_nueva("restaurante"), {**datos, "autoriza_datos": "on"})
    assert VentaRestauranteRemision.objects.count() == 1
    restaurante_sin_autorizar.refresh_from_db()
    assert restaurante_sin_autorizar.autoriza_tratamiento_datos is True


def test_un_error_de_existencia_se_muestra(client, admin_pdv, punto_venta, con_stock):
    client.force_login(admin_pdv)
    datos = _datos(punto_venta, con_stock, "31", numero_factura_siigo="FE-1")
    respuesta = client.post(_nueva("consumidor"), datos)
    assert "No hay existencia suficiente" in respuesta.content.decode()


def test_un_canal_que_no_existe_da_404(client, admin_pdv):
    client.force_login(admin_pdv)
    assert client.get(_nueva("mayorista")).status_code == 404


# --- Alcance -----------------------------------------------------------------


def test_el_pdv_vende_solo_en_su_punto(client, admin_pdv, otro_punto, gerente):
    """RN-06: aunque pida otro punto, el formulario es del suyo."""
    client.force_login(admin_pdv)
    respuesta = client.get(_nueva("consumidor"), {"ubicacion": otro_punto.pk})
    assert respuesta.context["punto"] == admin_pdv.ubicacion


def test_el_pdv_no_ve_ventas_de_otro_punto(client, admin_pdv, otro_punto, gerente, producto):
    registrar_movimiento_pdv(
        ubicacion=otro_punto,
        producto=producto,
        tipo="ENTRADA_TRASLADO",
        cantidad="5",
        usuario=gerente,
    )
    ajena = registrar_venta_consumidor(
        ubicacion=otro_punto,
        numero_factura_siigo="FE-9",
        lineas=[linea(producto, "1")],
        usuario=gerente,
    )
    client.force_login(admin_pdv)
    url = reverse("puntoventa:venta_detalle", args=["consumidor", ajena.pk])
    assert client.get(url).status_code == 403


def test_el_gerente_elige_el_punto_y_vende(client, gerente, punto_venta, otro_punto, con_stock):
    client.force_login(gerente)
    respuesta = client.get(_nueva("consumidor"), {"ubicacion": punto_venta.pk})
    assert respuesta.context["punto"] == punto_venta
    client.post(_nueva("consumidor"), _datos(punto_venta, con_stock, numero_factura_siigo="FE-5"))
    assert existencia_pdv(con_stock, punto_venta) == Decimal("25")


def test_consulta_lee_pero_no_vende(client, consulta, punto_venta, con_stock):
    client.force_login(consulta)
    lista = client.get(reverse("puntoventa:venta_lista"))
    assert lista.status_code == 200
    assert lista.context["puede_vender"] is False
    assert client.get(_nueva("consumidor")).status_code == 403


def test_bodega_no_entra_al_punto_de_venta(client, jefe_bodega, punto_venta):
    client.force_login(jefe_bodega)
    for nombre in ("venta_lista", "historial", "existencias"):
        assert client.get(reverse(f"puntoventa:{nombre}")).status_code == 403
    assert client.get(_nueva("consumidor")).status_code == 403


# --- Historial, tablero y menú -----------------------------------------------


def test_el_historial_muestra_entradas_y_ventas(client, admin_pdv, punto_venta, con_stock):
    registrar_venta_consumidor(
        ubicacion=punto_venta,
        numero_factura_siigo="FE-3",
        lineas=[linea(con_stock, "2")],
        usuario=admin_pdv,
    )
    client.force_login(admin_pdv)
    respuesta = client.get(reverse("puntoventa:historial"))
    contenido = respuesta.content.decode()
    assert respuesta.context["pagina"].paginator.count == 2
    assert "Entrada por traslado" in contenido
    assert "30,00 kg" in contenido  # lo que entró
    assert "2,00 kg" in contenido  # lo que se vendió


def test_un_rango_al_reves_avisa(client, admin_pdv):
    client.force_login(admin_pdv)
    respuesta = client.get(
        reverse("puntoventa:historial"), {"desde": "2026-10-20", "hasta": "2026-10-10"}
    )
    assert "La fecha inicial no puede ser posterior" in respuesta.content.decode()


def test_el_tablero_del_pdv_muestra_las_ventas_de_hoy(client, admin_pdv, punto_venta, con_stock):
    registrar_venta_consumidor(
        ubicacion=punto_venta,
        numero_factura_siigo="FE-4",
        lineas=[linea(con_stock, "2")],
        usuario=admin_pdv,
    )
    client.force_login(admin_pdv)
    respuesta = client.get(reverse("inicio"))
    assert respuesta.context["ventas_hoy"] == {"ventas": 1, "kg": Decimal("2")}
    assert "Ventas de hoy" in respuesta.content.decode()


def test_el_menu_del_pdv_lleva_a_ventas_e_historial(client, admin_pdv):
    client.force_login(admin_pdv)
    contenido = client.get(reverse("inicio")).content.decode()
    for nombre in ("venta_lista", "existencias", "historial"):
        assert reverse(f"puntoventa:{nombre}") in contenido
