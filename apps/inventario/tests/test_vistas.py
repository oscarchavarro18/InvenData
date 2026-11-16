from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import Existencia, Lote


@pytest.fixture
def con_sesion(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def test_exige_iniciar_sesion(client, db):
    respuesta = client.get(reverse("inventario:existencias"))
    assert respuesta.status_code == 302
    assert "/login/" in respuesta["Location"]


def test_vacio_explica_como_aparece_el_producto(con_sesion):
    contenido = con_sesion.get(reverse("inventario:existencias")).content.decode()
    assert "Todavía no hay producto en bodega" in contenido


def test_lista_la_existencia_por_lote_y_ubicacion(con_sesion, lote, bodega, tunel):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("30"))
    Existencia.objects.create(lote=lote, ubicacion=tunel, cantidad=Decimal("12.50"))

    respuesta = con_sesion.get(reverse("inventario:existencias"))

    contenido = respuesta.content.decode()
    assert "L-000001" in contenido
    assert "Pechuga" in contenido
    assert "Cuarto de sostenimiento" in contenido
    assert "30,00 kg" in contenido
    assert "42,50" in contenido  # total en bodega
    assert respuesta.context["pagina"].paginator.count == 2


def test_no_muestra_existencia_en_cero(con_sesion, lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("0"))
    respuesta = con_sesion.get(reverse("inventario:existencias"))
    assert respuesta.context["pagina"].paginator.count == 0


def test_busca_por_producto_o_lote(con_sesion, lote, datos_lote, bodega):
    otro = Lote.objects.create(codigo="L-000002", origen="INVENTARIO_INICIAL", **datos_lote)
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("5"))
    Existencia.objects.create(lote=otro, ubicacion=bodega, cantidad=Decimal("6"))

    por_lote = con_sesion.get(reverse("inventario:existencias"), {"q": "000002"})
    assert [f.lote.codigo for f in por_lote.context["pagina"]] == ["L-000002"]

    por_producto = con_sesion.get(reverse("inventario:existencias"), {"q": "pechuga"})
    assert por_producto.context["pagina"].paginator.count == 2

    ninguno = con_sesion.get(reverse("inventario:existencias"), {"q": "camarón"})
    assert "Ninguna existencia coincide" in ninguno.content.decode()


def test_filtra_por_ubicacion(con_sesion, lote, bodega, tunel):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("30"))
    Existencia.objects.create(lote=lote, ubicacion=tunel, cantidad=Decimal("12"))

    respuesta = con_sesion.get(reverse("inventario:existencias"), {"ubicacion": str(tunel.pk)})

    (fila,) = respuesta.context["pagina"]
    assert fila.ubicacion == tunel


def test_ignora_una_ubicacion_que_no_es_numero(con_sesion, lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("30"))
    respuesta = con_sesion.get(reverse("inventario:existencias"), {"ubicacion": "abc"})
    assert respuesta.status_code == 200
    assert respuesta.context["pagina"].paginator.count == 1


def test_marca_los_lotes_vencidos(con_sesion, datos_lote, bodega):
    ayer = timezone.localdate() - timedelta(days=1)
    vencido = Lote.objects.create(
        codigo="L-V", origen="INVENTARIO_INICIAL", **{**datos_lote, "fecha_vencimiento": ayer}
    )
    Existencia.objects.create(lote=vencido, ubicacion=bodega, cantidad=Decimal("5"))
    contenido = con_sesion.get(reverse("inventario:existencias")).content.decode()
    assert "Vencido" in contenido
