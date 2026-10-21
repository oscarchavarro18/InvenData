"""Pantallas de lotes, pesadas y cierre de documentos del proveedor."""

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventario.models import Existencia, Lote, Movimiento
from apps.recepcion.models import DocumentoProveedor, Recepcion
from apps.recepcion.servicios import crear_lote_recepcion, registrar_pesada


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def _datos_pesada(canastilla, tunel, **cambios):
    datos = {
        "tipo_embalaje": canastilla.pk,
        "cantidad_embalajes": 10,
        "peso_bruto": "125.00",
        "temperatura": "3.5",
        "ubicacion_destino": tunel.pk,
    }
    datos.update(cambios)
    return datos


def _detalle(linea):
    return reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])


# --- Crear lote -------------------------------------------------------------------


def test_crear_un_lote_desde_la_pantalla(cliente, linea):
    respuesta = cliente.post(
        reverse("recepcion:lote_crear", args=[linea.pk]),
        {"estado_producto": "FRESCO", "fecha_vencimiento": "2026-12-05"},
    )
    assert respuesta.status_code == 302
    lote = Lote.objects.get()
    assert lote.codigo.startswith("L-")
    assert lote.estado_producto == "FRESCO"
    assert lote.fecha_vencimiento == date(2026, 12, 5)


def test_un_lote_con_datos_invalidos_avisa_y_no_se_crea(cliente, linea):
    respuesta = cliente.post(
        reverse("recepcion:lote_crear", args=[linea.pk]),
        {"estado_producto": "ROTO", "fecha_vencimiento": ""},
        follow=True,
    )
    assert Lote.objects.count() == 0
    mensajes = [str(m) for m in respuesta.context["messages"]]
    assert any("Estado" in m for m in mensajes)
    assert any("Vence" in m for m in mensajes)


def test_no_se_crea_un_lote_que_vence_antes_del_documento(cliente, linea):
    respuesta = cliente.post(
        reverse("recepcion:lote_crear", args=[linea.pk]),
        {"estado_producto": "FRESCO", "fecha_vencimiento": "2026-09-01"},
        follow=True,
    )
    assert Lote.objects.count() == 0
    assert any("antes de la fecha" in str(m) for m in respuesta.context["messages"])


def test_eliminar_un_lote_sin_pesadas(cliente, lote):
    respuesta = cliente.post(reverse("recepcion:lote_eliminar", args=[lote.pk]))
    assert respuesta.status_code == 302
    assert Lote.objects.count() == 0


def test_no_se_elimina_un_lote_con_pesadas(cliente, lote, canastilla, tunel, jefe_bodega):
    registrar_pesada(
        lote=lote,
        tipo_embalaje=canastilla,
        cantidad_embalajes=1,
        peso_bruto=Decimal("30"),
        temperatura=Decimal("2"),
        ubicacion_destino=tunel,
        usuario=jefe_bodega,
    )
    respuesta = cliente.post(reverse("recepcion:lote_eliminar", args=[lote.pk]), follow=True)
    assert Lote.objects.count() == 1
    assert any("ya tiene pesadas" in str(m) for m in respuesta.context["messages"])


# --- Registrar pesada -------------------------------------------------------------


def test_registrar_una_pesada_calcula_el_neto_y_guarda_al_responsable(
    cliente, lote, canastilla, tunel, jefe_bodega
):
    respuesta = cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]), _datos_pesada(canastilla, tunel)
    )
    assert respuesta.status_code == 302
    tanda = Recepcion.objects.get()
    assert tanda.peso_neto == Decimal("100.00")  # 125 - 10 × 2,50
    assert tanda.responsable == jefe_bodega
    assert tanda.ubicacion_destino == tunel
    assert Existencia.objects.count() == 0  # pesar no mueve inventario


def test_la_pesada_aparece_en_el_detalle_con_la_diferencia_en_vivo(
    cliente, linea, lote, canastilla, tunel
):
    cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]), _datos_pesada(canastilla, tunel)
    )
    contenido = cliente.get(_detalle(linea)).content.decode()
    assert "100,00" in contenido  # neto
    assert "Completo" in contenido  # declarado 100 kg = recibido 100 kg


@pytest.mark.parametrize(
    ("cambios", "texto"),
    [
        ({"peso_bruto": "0"}, "Peso bruto"),
        ({"peso_bruto": "abc"}, "Peso bruto"),
        ({"temperatura": ""}, "Temp."),
        ({"cantidad_embalajes": "-1"}, "Cant."),
        ({"cantidad_embalajes": "50"}, "tara"),  # 50 × 2,50 = 125 → neto 0
    ],
)
def test_una_pesada_invalida_avisa_y_no_se_guarda(cliente, lote, canastilla, tunel, cambios, texto):
    respuesta = cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]),
        _datos_pesada(canastilla, tunel, **cambios),
        follow=True,
    )
    assert Recepcion.objects.count() == 0
    assert any(texto in str(m) for m in respuesta.context["messages"])


def test_el_destino_debe_ser_una_ubicacion_de_recepcion(cliente, lote, canastilla, punto_venta):
    respuesta = cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]),
        _datos_pesada(canastilla, punto_venta),
        follow=True,
    )
    assert Recepcion.objects.count() == 0
    assert any("Destino" in str(m) for m in respuesta.context["messages"])


def test_la_pesada_solo_acepta_post(cliente, lote):
    assert cliente.get(reverse("recepcion:pesada_registrar", args=[lote.pk])).status_code == 405


# --- Cerrar documento -------------------------------------------------------------


@pytest.fixture
def pesado(lote, canastilla, tunel, jefe_bodega):
    """El lote de recepción con una pesada de 100 kg netos hacia el túnel."""
    registrar_pesada(
        lote=lote,
        tipo_embalaje=canastilla,
        cantidad_embalajes=10,
        peso_bruto=Decimal("125.00"),
        temperatura=Decimal("3.5"),
        ubicacion_destino=tunel,
        usuario=jefe_bodega,
    )
    return lote


def test_cerrar_el_documento_crea_la_existencia(cliente, linea, pesado, tunel):
    respuesta = cliente.post(
        reverse("recepcion:documento_cerrar", args=[linea.documento_proveedor_id]), follow=True
    )
    assert DocumentoProveedor.objects.get().estado == "CERRADO"
    assert Existencia.objects.get().cantidad == Decimal("100.00")
    assert Movimiento.objects.get().tipo == "RECEPCION"
    assert any("Documento cerrado" in str(m) for m in respuesta.context["messages"])
    assert "Ver inventario" in respuesta.content.decode()


def test_no_se_cierra_con_un_lote_sin_pesadas(cliente, linea, pesado, datos_lote):
    crear_lote_recepcion(linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 9))
    respuesta = cliente.post(
        reverse("recepcion:documento_cerrar", args=[linea.documento_proveedor_id]), follow=True
    )
    assert DocumentoProveedor.objects.get().estado == "ABIERTO"
    assert Existencia.objects.count() == 0
    assert any("sin pesadas" in str(m) for m in respuesta.context["messages"])


def test_el_detalle_deshabilita_el_cierre_mientras_falten_pesadas(cliente, linea, lote):
    contenido = cliente.get(_detalle(linea)).content.decode()
    assert "no tiene pesadas" in contenido
    assert "disabled" in contenido.split("Cerrar documento</button>")[0][-120:]


def test_el_detalle_habilita_el_cierre_cuando_todo_esta_pesado(cliente, linea, pesado):
    contenido = cliente.get(_detalle(linea)).content.decode()
    boton = contenido.split("Cerrar documento</button>")[0][-120:]
    assert "disabled" not in boton


def test_avisa_de_las_lineas_sin_lotes(cliente, linea, pesado, producto):
    from apps.maestros.models import Producto

    otro = Producto.objects.create(
        codigo="X-1", nombre="Otro", unidad_medida="KG", categoria=producto.categoria
    )
    cliente.post(
        reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id]),
        {"producto": otro.pk, "cantidad": "10"},
    )
    contenido = cliente.get(_detalle(linea)).content.decode()
    assert "Otro no tiene lotes" in contenido


def test_un_documento_cerrado_no_admite_mas_cambios(cliente, linea, pesado, canastilla, tunel):
    cliente.post(reverse("recepcion:documento_cerrar", args=[linea.documento_proveedor_id]))
    respuesta = cliente.post(
        reverse("recepcion:pesada_registrar", args=[pesado.pk]),
        _datos_pesada(canastilla, tunel),
        follow=True,
    )
    assert Recepcion.objects.count() == 1
    assert any("ya está cerrado" in str(m) for m in respuesta.context["messages"])
    contenido = cliente.get(_detalle(linea)).content.decode()
    assert "Registrar pesada" not in contenido
    assert "Cerrar documento</button>" not in contenido


def test_cerrar_dos_veces_avisa_sin_duplicar_movimientos(cliente, linea, pesado):
    url = reverse("recepcion:documento_cerrar", args=[linea.documento_proveedor_id])
    cliente.post(url)
    respuesta = cliente.post(url, follow=True)
    assert Movimiento.objects.count() == 1
    assert any("ya está cerrado" in str(m) for m in respuesta.context["messages"])


def test_los_formularios_de_pesada_no_consultan_la_base_por_cada_lote(
    cliente, linea, canastilla, tunel, django_assert_num_queries
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def consultas():
        with CaptureQueriesContext(connection) as capturadas:
            cliente.get(_detalle(linea))
        return len(capturadas)

    crear_lote_recepcion(linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1))
    con_uno = consultas()
    for dia in (2, 3, 4, 5):
        crear_lote_recepcion(
            linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, dia)
        )
    assert consultas() == con_uno
