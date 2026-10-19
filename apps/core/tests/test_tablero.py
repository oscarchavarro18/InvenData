from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventario.models import Existencia, Lote
from apps.recepcion.models import DocumentoProveedor


@pytest.fixture
def con_sesion(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def test_el_tablero_vacio_muestra_ceros(con_sesion):
    respuesta = con_sesion.get(reverse("inicio"))
    assert respuesta.status_code == 200
    assert respuesta.context["documentos_abiertos"] == 0
    assert respuesta.context["kg_en_bodega"] == Decimal("0")
    assert respuesta.context["n_por_vencer"] == 0
    contenido = respuesta.content.decode()
    assert "Todavía no hay recepciones" in contenido
    assert "No hay lotes por vencer" in contenido


def test_cuenta_los_documentos_abiertos_y_lista_los_recientes(con_sesion, linea):
    respuesta = con_sesion.get(reverse("inicio"))
    assert respuesta.context["documentos_abiertos"] == 1
    assert list(respuesta.context["recientes"]) == [linea.documento_proveedor]
    assert "FACTURA F-100" in respuesta.content.decode()


def test_los_documentos_cerrados_no_cuentan_como_abiertos(con_sesion, linea):
    DocumentoProveedor.objects.update(estado="CERRADO")
    assert con_sesion.get(reverse("inicio")).context["documentos_abiertos"] == 0


def test_muestra_existencia_y_lotes_por_vencer(con_sesion, lote, datos_lote, bodega):
    hoy = timezone.localdate()
    Lote.objects.filter(pk=lote.pk).update(fecha_vencimiento=hoy + timedelta(days=2))
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("42.50"))

    respuesta = con_sesion.get(reverse("inicio"))

    assert respuesta.context["kg_en_bodega"] == Decimal("42.50")
    assert respuesta.context["lotes_con_existencia"] == 1
    assert respuesta.context["n_por_vencer"] == 1
    contenido = respuesta.content.decode()
    assert "L-000001" in contenido
    assert "indicador__valor--critico" in contenido


def test_solo_muestra_cinco_lotes_por_vencer(con_sesion, datos_lote, bodega):
    hoy = timezone.localdate()
    for numero in range(7):
        lote = Lote.objects.create(
            codigo=f"L-{numero}",
            origen="INVENTARIO_INICIAL",
            **{**datos_lote, "fecha_vencimiento": hoy + timedelta(days=1)},
        )
        Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("1"))

    respuesta = con_sesion.get(reverse("inicio"))

    assert respuesta.context["n_por_vencer"] == 7
    assert len(respuesta.context["por_vencer"]) == 5


def test_el_menu_resalta_la_seccion_actual(con_sesion):
    contenido = con_sesion.get(reverse("inicio")).content.decode()
    activo = contenido.split("menu__item--activo")[1][:200]
    assert "Dashboard" in contenido
    assert reverse("inicio") in activo
    recepcion = con_sesion.get(reverse("recepcion:documento_lista")).content.decode()
    assert reverse("recepcion:documento_lista") in recepcion.split("menu__item--activo")[1][:200]
