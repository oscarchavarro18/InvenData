"""Pantalla de traslado interno entre zonas (RF-19, RF-02)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.inventario.models import Movimiento
from apps.inventario.servicios import existencia_de, registrar_movimiento


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="30", usuario=gerente, ubicacion_destino=bodega
    )
    return lote


@pytest.fixture
def url(en_bodega, bodega):
    return reverse("inventario:trasladar", args=[en_bodega.pk, bodega.pk])


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def test_el_formulario_muestra_el_origen_y_sugiere_todo_lo_disponible(cliente, url):
    respuesta = cliente.get(url)
    contenido = respuesta.content.decode()
    assert respuesta.status_code == 200
    assert "Lote L-000001" in contenido
    assert "Cuarto de sostenimiento" in contenido
    assert respuesta.context["form"].initial["cantidad"] == Decimal("30")


def test_el_destino_no_ofrece_el_origen_ni_los_puntos_de_venta(
    cliente, url, bodega, tunel, punto_venta
):
    destinos = list(cliente.get(url).context["form"].fields["destino"].queryset)
    assert destinos == [tunel]


def test_trasladar_mueve_el_saldo_y_vuelve_al_inventario(cliente, url, en_bodega, bodega, tunel):
    respuesta = cliente.post(
        url, {"destino": tunel.pk, "cantidad": "12.5", "observacion": ""}, follow=True
    )

    assert respuesta.redirect_chain[-1][0] == reverse("inventario:existencias")
    assert "Se trasladaron 12.50 kg del lote L-000001" in respuesta.content.decode()
    assert existencia_de(en_bodega, bodega) == Decimal("17.50")
    assert existencia_de(en_bodega, tunel) == Decimal("12.50")
    assert Auditoria.objects.filter(entidad="movimiento").count() == 1


def test_un_error_de_negocio_se_muestra_en_el_formulario(cliente, url, en_bodega, bodega, tunel):
    respuesta = cliente.post(url, {"destino": tunel.pk, "cantidad": "31"})

    assert respuesta.status_code == 200
    assert "No hay existencia suficiente" in respuesta.content.decode()
    assert existencia_de(en_bodega, bodega) == Decimal("30")
    assert not Movimiento.objects.filter(tipo="TRASLADO_INTERNO").exists()


def test_un_destino_fuera_de_la_lista_se_rechaza(cliente, url, punto_venta, en_bodega, bodega):
    respuesta = cliente.post(url, {"destino": punto_venta.pk, "cantidad": "1"})
    assert respuesta.status_code == 200
    assert respuesta.context["form"].errors["destino"]
    assert existencia_de(en_bodega, bodega) == Decimal("30")


def test_sin_existencia_en_esa_ubicacion_responde_404(cliente, en_bodega, tunel):
    url = reverse("inventario:trasladar", args=[en_bodega.pk, tunel.pk])
    assert cliente.get(url).status_code == 404


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_sin_perfil_de_bodega_recibe_403(request, client, perfil, url, tunel, en_bodega, bodega):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(url).status_code == 403
    assert client.post(url, {"destino": tunel.pk, "cantidad": "1"}).status_code == 403
    assert existencia_de(en_bodega, bodega) == Decimal("30")


def test_consulta_no_ve_el_boton_de_trasladar(client, consulta, en_bodega):
    client.force_login(consulta)
    contenido = client.get(reverse("inventario:existencias")).content.decode()
    assert "L-000001" in contenido
    assert "Trasladar" not in contenido


def test_el_jefe_de_bodega_ve_el_boton_de_trasladar(cliente, url):
    contenido = cliente.get(reverse("inventario:existencias")).content.decode()
    assert url in contenido
