"""Pantallas de pedidos y alistamiento, y sus permisos (RF-32 a RF-34, RF-02, RN-06)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.embultaje.models import AlistamientoDetalle, Pedido


@pytest.fixture
def cliente_web(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def lotes(con_existencia, zona_bultos, bodega):
    return con_existencia("L-VIEJO", "40", zona_bultos, dias=10), con_existencia(
        "L-NUEVO", "50", bodega, dias=2
    )


def _detalle(pedido):
    return reverse("embultaje:pedido_detalle", args=[pedido.pk])


def _asignar(linea, lote, ubicacion, cantidad, justificacion=""):
    prefijo = f"l{linea.pk}"
    return {
        f"{prefijo}-candidato": f"{lote.pk}-{ubicacion.pk}",
        f"{prefijo}-cantidad": cantidad,
        f"{prefijo}-justificacion": justificacion,
    }


# --- Lista y creación --------------------------------------------------------


def test_la_lista_muestra_los_pedidos_y_filtra_por_estado(client, consulta, pedido):
    client.force_login(consulta)
    respuesta = client.get(reverse("embultaje:pedido_lista"))
    assert pedido.consecutivo in respuesta.content.decode()
    anulados = client.get(reverse("embultaje:pedido_lista"), {"estado": "ANULADO"})
    assert anulados.context["pagina"].paginator.count == 0


def test_crear_un_pedido_lleva_a_su_detalle(cliente_web, cliente):
    respuesta = cliente_web.post(
        reverse("embultaje:pedido_crear"),
        {"cliente": cliente.pk, "fecha": timezone.localdate().isoformat()},
        follow=True,
    )
    pedido = Pedido.objects.get()
    assert respuesta.redirect_chain[-1][0] == _detalle(pedido)
    assert "Agregue sus líneas" in respuesta.content.decode()


def test_agregar_una_linea_repetida_muestra_el_error(cliente_web, pedido, producto):
    respuesta = cliente_web.post(
        reverse("embultaje:linea_agregar", args=[pedido.pk]),
        {"producto": producto.pk, "cantidad_solicitada": "5"},
        follow=True,
    )
    assert "ya tiene una línea de Pechuga" in respuesta.content.decode()


# --- Alistamiento ------------------------------------------------------------


def test_el_detalle_ofrece_fifo_y_marca_el_lote_sugerido(cliente_web, pedido, lotes):
    contenido = cliente_web.get(_detalle(pedido)).content.decode()
    assert "Sugerir por FIFO" in contenido
    assert "L-VIEJO · Zona de bultos · 40.00 kg (sugerido FIFO)" in contenido


def test_sugerir_por_fifo_desde_la_pantalla(cliente_web, pedido, lotes):
    linea = pedido.lineas.get()
    respuesta = cliente_web.post(reverse("embultaje:linea_sugerir", args=[linea.pk]), follow=True)
    assert "Se asignaron 2 lote(s)" in respuesta.content.decode()
    assert AlistamientoDetalle.objects.count() == 2


def test_elegir_otro_lote_sin_justificar_muestra_el_error(cliente_web, pedido, lotes, bodega):
    linea = pedido.lineas.get()
    url = reverse("embultaje:linea_asignar", args=[linea.pk])

    sin_motivo = cliente_web.post(url, _asignar(linea, lotes[1], bodega, "20"), follow=True)
    assert "justifique por escrito" in sin_motivo.content.decode()
    assert not AlistamientoDetalle.objects.exists()

    cliente_web.post(url, _asignar(linea, lotes[1], bodega, "20", "Lo pidió fresco"))
    detalle = AlistamientoDetalle.objects.get()
    assert detalle.sugerido_por_fifo is False


def test_marcar_alistado_cierra_la_edicion(cliente_web, pedido, lotes):
    linea = pedido.lineas.get()
    cliente_web.post(reverse("embultaje:linea_sugerir", args=[linea.pk]))
    respuesta = cliente_web.post(reverse("embultaje:pedido_alistar", args=[pedido.pk]), follow=True)
    pedido.refresh_from_db()
    contenido = respuesta.content.decode()
    assert pedido.estado == "ALISTADO"
    assert "listo para despacho" in contenido
    assert "Sugerir por FIFO" not in contenido


# --- Anulación ---------------------------------------------------------------


def test_solo_el_gerente_ve_y_usa_la_anulacion(client, jefe_bodega, gerente, pedido):
    url = reverse("embultaje:pedido_anular", args=[pedido.pk])
    client.force_login(jefe_bodega)
    assert "Anular pedido" not in client.get(_detalle(pedido)).content.decode()
    assert client.post(url, {"observacion": "x"}).status_code == 403

    client.force_login(gerente)
    sin_motivo = client.post(url, {"observacion": ""}, follow=True)
    assert "Motivo de la anulación: " in sin_motivo.content.decode()  # el error del campo
    pedido.refresh_from_db()
    assert pedido.estado == "CREADO"
    client.post(url, {"observacion": "Cliente canceló"})
    pedido.refresh_from_db()
    assert pedido.estado == "ANULADO"


# --- Permisos ----------------------------------------------------------------


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_sin_perfil_de_bodega_no_se_operan_pedidos(request, client, perfil, pedido):
    client.force_login(request.getfixturevalue(perfil))
    linea = pedido.lineas.get()
    urls = [
        reverse("embultaje:pedido_crear"),
        reverse("embultaje:linea_agregar", args=[pedido.pk]),
        reverse("embultaje:linea_sugerir", args=[linea.pk]),
        reverse("embultaje:linea_asignar", args=[linea.pk]),
        reverse("embultaje:pedido_alistar", args=[pedido.pk]),
    ]
    for url in urls:
        assert client.post(url, {}).status_code == 403
    pedido.refresh_from_db()
    assert pedido.estado == "CREADO"


def test_el_administrador_de_pdv_no_ve_los_pedidos(client, admin_pdv, pedido):
    """RN-06: el alistamiento es un proceso de bodega."""
    client.force_login(admin_pdv)
    assert client.get(reverse("embultaje:pedido_lista")).status_code == 403
    assert client.get(_detalle(pedido)).status_code == 403


def test_el_menu_resalta_pedidos_y_no_embultaje(cliente_web):
    contenido = cliente_web.get(reverse("embultaje:pedido_lista")).content.decode()
    activo = contenido.split("menu__item--activo")[1][:200]
    assert reverse("embultaje:pedido_lista") in activo
    assert contenido.count("menu__item--activo") == 1
