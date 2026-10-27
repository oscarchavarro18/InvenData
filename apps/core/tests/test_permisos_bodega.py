"""El administrador de punto de venta nunca ve la bodega (RN-06); los demás perfiles sí."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import Existencia, Lote


@pytest.fixture
def por_vencer(lote, bodega):
    Lote.objects.filter(pk=lote.pk).update(fecha_vencimiento=timezone.localdate() + timedelta(1))
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("42.50"))
    return lote


def test_el_administrador_de_pdv_recibe_403_en_el_inventario(client, admin_pdv):
    client.force_login(admin_pdv)
    respuesta = client.get(reverse("inventario:existencias"))
    assert respuesta.status_code == 403
    assert "No tiene permiso" in respuesta.content.decode()


def test_el_tablero_no_le_muestra_nada_de_bodega(client, admin_pdv, por_vencer, linea):
    client.force_login(admin_pdv)
    respuesta = client.get(reverse("inicio"))
    contenido = respuesta.content.decode()

    assert respuesta.status_code == 200
    assert "kg_en_bodega" not in respuesta.context
    for texto in ("Existencia en bodega", "42,50", "L-000001", "FACTURA F-100", "Por vencer"):
        assert texto not in contenido
    assert "módulo de punto de venta" in contenido


def test_el_administrador_de_pdv_recibe_403_en_configuracion(client, admin_pdv):
    """Configuración lista las zonas y los embalajes de la bodega."""
    client.force_login(admin_pdv)
    assert client.get(reverse("maestros:configuracion")).status_code == 403


def test_el_menu_no_le_muestra_recepcion_inventario_ni_configuracion(client, admin_pdv):
    client.force_login(admin_pdv)
    contenido = client.get(reverse("inicio")).content.decode()
    assert reverse("inventario:existencias") not in contenido
    assert reverse("recepcion:documento_lista") not in contenido
    assert reverse("maestros:configuracion") not in contenido
    assert reverse("maestros:producto_lista") in contenido  # el catálogo sí, lo usará en M7


def test_el_administrador_de_pdv_si_ve_el_catalogo_de_productos(client, admin_pdv):
    client.force_login(admin_pdv)
    assert client.get(reverse("maestros:producto_lista")).status_code == 200


def test_consulta_si_ve_la_bodega(client, consulta, por_vencer):
    client.force_login(consulta)
    tablero = client.get(reverse("inicio"))
    assert tablero.context["kg_en_bodega"] == Decimal("42.50")
    assert reverse("inventario:existencias") in tablero.content.decode()
    assert reverse("recepcion:documento_lista") in tablero.content.decode()
    assert client.get(reverse("inventario:existencias")).status_code == 200
    assert client.get(reverse("maestros:configuracion")).status_code == 200
    assert reverse("maestros:configuracion") in tablero.content.decode()


def test_un_lote_por_vencer_del_tablero_enlaza_a_su_historial(client, jefe_bodega, por_vencer):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("inicio")).content.decode()
    assert reverse("inventario:lote_detalle", args=[por_vencer.pk]) in contenido
