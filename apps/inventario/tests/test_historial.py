"""Historial de un lote, desde su ingreso hasta su destino final (RF-22, RN-17, RN-18)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventario.consultas import existencia_del_lote, historial_de_lote
from apps.inventario.models import Lote
from apps.inventario.servicios import (
    registrar_movimiento,
    reversar_movimiento,
    trasladar_entre_zonas,
)


@pytest.fixture
def con_historia(lote, bodega, tunel, gerente):
    """Recepción de 30 kg, traslado de 10 al túnel y despacho de 5 desde el túnel."""
    inicio = timezone.now() - timedelta(days=3)
    registrar_movimiento(
        lote=lote,
        tipo="RECEPCION",
        cantidad="30",
        usuario=gerente,
        ubicacion_destino=bodega,
        fecha_hora=inicio,
    )
    trasladar_entre_zonas(lote=lote, origen=bodega, destino=tunel, cantidad="10", usuario=gerente)
    registrar_movimiento(
        lote=lote,
        tipo="DESPACHO_MAYORISTA",
        cantidad="5",
        usuario=gerente,
        ubicacion_origen=tunel,
    )
    return lote


@pytest.fixture
def url(lote):
    return reverse("inventario:lote_detalle", args=[lote.pk])


# --- Consulta ----------------------------------------------------------------


def test_el_historial_va_en_orden_cronologico(con_historia):
    tipos = [m.tipo for m in historial_de_lote(con_historia)]
    assert tipos == ["RECEPCION", "TRASLADO_INTERNO", "DESPACHO_MAYORISTA"]


def test_cada_movimiento_se_clasifica_como_entrada_salida_o_traslado(con_historia):
    sentidos = [m.sentido for m in historial_de_lote(con_historia)]
    assert sentidos == ["ENTRADA", "TRASLADO", "SALIDA"]


def test_un_reverso_aparece_en_el_historial_y_marca_al_original(con_historia, gerente):
    traslado = con_historia.movimientos.get(tipo="TRASLADO_INTERNO")
    # Primero se devuelve lo despachado, para que el túnel tenga los 10 kg del traslado.
    despacho = con_historia.movimientos.get(tipo="DESPACHO_MAYORISTA")
    reversar_movimiento(movimiento=despacho, usuario=gerente, observacion="Despacho mal digitado")
    reversar_movimiento(movimiento=traslado, usuario=gerente, observacion="Zona equivocada")

    historial = list(historial_de_lote(con_historia))

    assert len(historial) == 3 + 1 + 2  # el traslado se compensa con dos ajustes
    original = next(m for m in historial if m.pk == traslado.pk)
    assert original.reversado is True
    reversos = [m for m in historial if m.movimiento_reversado_id == traslado.pk]
    assert {m.sentido for m in reversos} == {"ENTRADA", "SALIDA"}


def test_la_existencia_del_lote_muestra_solo_saldos_positivos(con_historia, bodega, tunel):
    saldos = {e.ubicacion: e.cantidad for e in existencia_del_lote(con_historia)}
    assert saldos == {bodega: Decimal("20"), tunel: Decimal("5")}


def test_el_historial_no_mezcla_lotes(con_historia, datos_lote, bodega, gerente):
    otro = Lote.objects.create(codigo="L-OTRO", origen="INVENTARIO_INICIAL", **datos_lote)
    registrar_movimiento(
        lote=otro,
        tipo="INVENTARIO_INICIAL",
        cantidad="1",
        usuario=gerente,
        ubicacion_destino=bodega,
    )
    assert historial_de_lote(otro).count() == 1
    assert historial_de_lote(con_historia).count() == 3


# --- Pantalla ----------------------------------------------------------------


def test_la_pantalla_muestra_datos_existencia_y_movimientos(client, jefe_bodega, con_historia, url):
    client.force_login(jefe_bodega)
    respuesta = client.get(url)
    contenido = respuesta.content.decode()

    assert respuesta.status_code == 200
    assert "Lote L-000001" in contenido
    assert "Pechuga" in contenido
    assert "FACTURA F-100" in contenido  # documento del proveedor de donde viene
    assert "Túnel de congelación 1" in contenido
    assert "25,00 kg" in contenido  # existencia total
    assert respuesta.context["pagina"].paginator.count == 3
    for texto in ("Entrada", "Traslado", "Salida", "Despacho a mayorista"):
        assert texto in contenido


def test_un_lote_sin_movimientos_lo_explica(client, consulta, lote, url):
    client.force_login(consulta)
    contenido = client.get(url).content.decode()
    assert "todavía no tiene movimientos" in contenido
    assert "ya no tiene existencia en bodega" in contenido


def test_el_historial_se_pagina(client, gerente, lote, bodega, url):
    for _ in range(25):
        registrar_movimiento(
            lote=lote, tipo="RECEPCION", cantidad="1", usuario=gerente, ubicacion_destino=bodega
        )
    client.force_login(gerente)
    pagina_2 = client.get(url, {"pagina": 2}).context["pagina"]
    assert pagina_2.paginator.count == 25
    assert len(pagina_2.object_list) == 5


def test_un_lote_que_no_existe_responde_404(client, gerente, db):
    client.force_login(gerente)
    assert client.get(reverse("inventario:lote_detalle", args=[999])).status_code == 404


def test_la_existencia_enlaza_al_historial(client, jefe_bodega, con_historia, url):
    client.force_login(jefe_bodega)
    assert url in client.get(reverse("inventario:existencias")).content.decode()


def test_el_administrador_de_pdv_no_ve_el_historial(client, admin_pdv, con_historia, url):
    """RN-06: el administrador de punto de venta nunca ve la bodega."""
    client.force_login(admin_pdv)
    assert client.get(url).status_code == 403
