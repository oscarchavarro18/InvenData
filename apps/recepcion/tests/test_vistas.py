from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.recepcion.models import DocumentoProveedorLinea
from apps.recepcion.servicios import cerrar_documento, crear_lote_recepcion, registrar_pesada


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def pesar(canastilla, jefe_bodega, tunel):
    def _pesar(lote):
        return registrar_pesada(
            lote=lote,
            tipo_embalaje=canastilla,
            cantidad_embalajes=5,
            peso_bruto=Decimal("50.00"),
            temperatura=Decimal("3.00"),
            ubicacion_destino=tunel,
            usuario=jefe_bodega,
        )

    return _pesar


# --- Acceso -----------------------------------------------------------------------


def test_la_lista_exige_iniciar_sesion(client):
    respuesta = client.get(reverse("recepcion:documento_lista"))
    assert respuesta.status_code == 302
    assert respuesta.url.startswith(reverse("login"))


def test_el_detalle_exige_iniciar_sesion(client, linea):
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    assert client.get(url).status_code == 302


# --- Lista ------------------------------------------------------------------------


def test_la_lista_muestra_los_documentos(cliente, linea):
    respuesta = cliente.get(reverse("recepcion:documento_lista"))
    assert respuesta.status_code == 200
    contenido = respuesta.content.decode()
    assert "F-100" in contenido
    assert "Avícola del Huila" in contenido
    assert "Abierto" in contenido


def test_la_lista_cuenta_las_lineas_de_cada_documento(cliente, linea, producto):
    DocumentoProveedorLinea.objects.create(
        documento_proveedor=linea.documento_proveedor, producto=producto, cantidad=Decimal("10")
    )
    respuesta = cliente.get(reverse("recepcion:documento_lista"))
    (documento,) = respuesta.context["documentos"]
    assert documento.n_lineas == 2


def test_la_lista_vacia_avisa(cliente):
    respuesta = cliente.get(reverse("recepcion:documento_lista"))
    assert "Todavía no hay documentos" in respuesta.content.decode()


# --- Detalle ----------------------------------------------------------------------


def test_el_detalle_de_un_documento_inexistente_da_404(cliente):
    assert cliente.get(reverse("recepcion:documento_detalle", args=[999])).status_code == 404


def test_el_detalle_muestra_lotes_y_tandas(cliente, linea, lote, pesar):
    pesar(lote)
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    contenido = cliente.get(url).content.decode()
    assert "Pechuga" in contenido
    assert "Lote L-000001" in contenido
    assert "Canastilla" in contenido


def test_abierto_la_diferencia_se_calcula_en_vivo(cliente, linea, lote, pesar):
    pesar(lote)  # 37.50 de 100 declarados
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    (fila,) = cliente.get(url).context["filas"]
    assert fila["recibido"] == Decimal("37.50")
    assert fila["diferencia"] == Decimal("62.50")
    assert fila["lotes"][0]["total"] == Decimal("37.50")


def test_cerrado_se_muestran_los_valores_congelados(cliente, linea, lote, pesar, gerente):
    pesar(lote)
    cerrar_documento(documento=linea.documento_proveedor, usuario=gerente)
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    respuesta = cliente.get(url)
    (fila,) = respuesta.context["filas"]
    assert fila["recibido"] == Decimal("37.50")
    assert fila["diferencia"] == Decimal("62.50")
    assert "Cerrado" in respuesta.content.decode()


def test_una_linea_sin_lotes_lo_avisa(cliente, linea):
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    contenido = cliente.get(url).content.decode()
    assert "todavía no tiene lotes" in contenido


def test_el_detalle_no_hace_consultas_de_mas(
    cliente, linea, lote, pesar, django_assert_max_num_queries
):
    pesar(lote)
    pesar(lote)
    for dia in (10, 20, 25):
        otro = crear_lote_recepcion(
            linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, dia)
        )
        pesar(otro)
        pesar(otro)
    url = reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])
    # Sesión, usuario y perfil, documento, líneas, lotes y tandas, más las listas de los
    # formularios (productos, embalajes, destinos): no crece con la cantidad de lotes.
    with django_assert_max_num_queries(13):
        assert cliente.get(url).status_code == 200
