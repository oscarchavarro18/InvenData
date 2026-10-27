"""Pantallas de transformación y sus permisos (RF-23 a RF-29, RF-02, RN-05, RN-06)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventario.servicios import existencia_de
from apps.transformacion.forms import FILAS_DE_DERIVADOS
from apps.transformacion.models import OrdenTransformacion


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def _url(nombre, orden):
    return reverse(f"transformacion:{nombre}", args=[orden.pk])


def _confirmacion(orden, filas, observacion=""):
    """POST como lo envía el navegador: las filas sin tocar llegan con sus valores propuestos."""
    lote = orden.lote_origen
    datos = {
        "form-TOTAL_FORMS": str(FILAS_DE_DERIVADOS),
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "observacion": observacion,
    }
    for i in range(FILAS_DE_DERIVADOS):
        fila = {
            "producto": lote.producto_id,
            "cantidad": "",
            "ubicacion_destino": orden.ubicacion_origen_id,
            "estado_producto": lote.estado_producto,
            "fecha_vencimiento": lote.fecha_vencimiento.isoformat(),
        }
        if i < len(filas):
            fila.update(filas[i])
        datos.update({f"form-{i}-{campo}": valor for campo, valor in fila.items()})
    return datos


# --- Lista y creación --------------------------------------------------------


def test_la_lista_muestra_las_ordenes_y_filtra_por_estado(client, consulta, orden):
    client.force_login(consulta)
    respuesta = client.get(reverse("transformacion:orden_lista"))
    assert orden.consecutivo in respuesta.content.decode()
    confirmadas = client.get(reverse("transformacion:orden_lista"), {"estado": "CONFIRMADA"})
    assert confirmadas.context["pagina"].paginator.count == 0


def test_el_inventario_ofrece_transformar_solo_lo_transformable(cliente, en_zona, zona):
    url = reverse("transformacion:orden_crear", args=[en_zona.pk, zona.pk])
    assert url in cliente.get(reverse("inventario:existencias")).content.decode()
    en_zona.producto.admite_transformacion = False
    en_zona.producto.save()
    assert url not in cliente.get(reverse("inventario:existencias")).content.decode()


def test_crear_una_orden_lleva_al_detalle_en_borrador(cliente, en_zona, zona):
    url = reverse("transformacion:orden_crear", args=[en_zona.pk, zona.pk])
    assert cliente.get(url).context["form"].initial["cantidad_consumida"] == Decimal("50")

    respuesta = cliente.post(url, {"cantidad_consumida": "40"}, follow=True)

    orden = OrdenTransformacion.objects.get()
    assert respuesta.redirect_chain[-1][0] == _url("orden_detalle", orden)
    assert "creada en borrador" in respuesta.content.decode()
    assert existencia_de(en_zona, zona) == Decimal("50")


def test_un_error_al_crear_se_muestra_en_el_formulario(cliente, en_zona, zona):
    url = reverse("transformacion:orden_crear", args=[en_zona.pk, zona.pk])
    respuesta = cliente.post(url, {"cantidad_consumida": "60"})
    assert respuesta.status_code == 200
    assert "No hay existencia suficiente" in respuesta.content.decode()
    assert not OrdenTransformacion.objects.exists()


# --- Detalle, edición y eliminación ------------------------------------------


def test_el_borrador_ofrece_registrar_derivados_y_confirmar(cliente, orden):
    respuesta = cliente.get(_url("orden_detalle", orden))
    contenido = respuesta.content.decode()
    assert "Confirmar transformación" in contenido
    assert "5 %" in contenido  # la tolerancia vigente
    assert len(respuesta.context["formset"].forms) == FILAS_DE_DERIVADOS


def test_consulta_ve_el_borrador_sin_formularios(client, consulta, orden):
    client.force_login(consulta)
    contenido = client.get(_url("orden_detalle", orden)).content.decode()
    assert "todavía no se ha confirmado" in contenido
    assert "Confirmar transformación" not in contenido


def test_editar_y_eliminar_el_borrador(cliente, orden):
    cliente.post(_url("orden_editar", orden), {"cantidad_consumida": "45"})
    orden.refresh_from_db()
    assert orden.cantidad_consumida == Decimal("45")

    respuesta = cliente.post(_url("orden_eliminar", orden))
    assert respuesta.url == reverse("transformacion:orden_lista")
    assert not OrdenTransformacion.objects.exists()


# --- Confirmación ------------------------------------------------------------


def test_confirmar_crea_los_derivados_y_muestra_el_balance(
    cliente, orden, en_zona, zona, porciones, tunel
):
    filas = [
        {"producto": porciones.pk, "cantidad": "30", "ubicacion_destino": tunel.pk},
        {"cantidad": "8"},  # reempaque del mismo producto, en la misma zona
    ]
    respuesta = cliente.post(
        _url("orden_confirmar", orden), _confirmacion(orden, filas), follow=True
    )

    orden.refresh_from_db()
    contenido = respuesta.content.decode()
    assert orden.estado == "CONFIRMADA"
    assert orden.derivados.count() == 2
    assert "se generaron 2 lotes derivados" in contenido
    assert "95,00 %" in contenido
    assert "Dentro de tolerancia" in contenido
    assert existencia_de(en_zona, zona) == Decimal("10")


def test_fuera_de_tolerancia_sin_observacion_muestra_el_error(cliente, orden, en_zona, zona):
    respuesta = cliente.post(
        _url("orden_confirmar", orden), _confirmacion(orden, [{"cantidad": "30"}])
    )
    assert respuesta.status_code == 200
    assert "escriba una observación" in respuesta.content.decode()
    orden.refresh_from_db()
    assert orden.estado == "BORRADOR"
    assert existencia_de(en_zona, zona) == Decimal("50")


def test_sin_derivados_muestra_el_error(cliente, orden):
    respuesta = cliente.post(_url("orden_confirmar", orden), _confirmacion(orden, []))
    assert "al menos un derivado" in respuesta.content.decode()


def test_el_lote_derivado_enlaza_a_su_orden(cliente, orden):
    cliente.post(_url("orden_confirmar", orden), _confirmacion(orden, [{"cantidad": "38"}]))
    lote = orden.derivados.get().lote_derivado
    contenido = cliente.get(reverse("inventario:lote_detalle", args=[lote.pk])).content.decode()
    assert _url("orden_detalle", orden) in contenido  # RF-28
    assert orden.lote_origen.codigo in contenido


# --- Permisos ----------------------------------------------------------------


@pytest.mark.parametrize("nombre", ["orden_editar", "orden_eliminar", "orden_confirmar"])
@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_sin_perfil_de_bodega_no_se_opera(request, client, perfil, nombre, orden):
    client.force_login(request.getfixturevalue(perfil))
    assert client.post(_url(nombre, orden), {}).status_code == 403
    assert OrdenTransformacion.objects.get().estado == "BORRADOR"


def test_consulta_no_puede_crear_ordenes(client, consulta, en_zona, zona):
    client.force_login(consulta)
    url = reverse("transformacion:orden_crear", args=[en_zona.pk, zona.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {"cantidad_consumida": "1"}).status_code == 403


def test_el_administrador_de_pdv_no_ve_la_transformacion(client, admin_pdv, orden):
    """RN-06: es un proceso de bodega."""
    client.force_login(admin_pdv)
    assert client.get(reverse("transformacion:orden_lista")).status_code == 403
    assert client.get(_url("orden_detalle", orden)).status_code == 403
    menu = client.get(reverse("inicio")).content.decode()
    assert reverse("transformacion:orden_lista") not in menu


def test_el_menu_ofrece_transformacion_al_jefe_de_bodega(cliente):
    contenido = cliente.get(reverse("inicio")).content.decode()
    assert reverse("transformacion:orden_lista") in contenido


@pytest.mark.parametrize(
    ("nombre", "datos"),
    [
        ("orden_editar", {"cantidad_consumida": "45"}),
        ("orden_eliminar", {}),
        ("orden_confirmar", None),
    ],
)
def test_una_orden_ya_confirmada_avisa_en_vez_de_cambiar(cliente, orden, nombre, datos):
    """Doble envío o botón «Atrás»: el error no se pierde y nada cambia."""
    cliente.post(_url("orden_confirmar", orden), _confirmacion(orden, [{"cantidad": "38"}]))
    if datos is None:
        datos = _confirmacion(orden, [{"cantidad": "38"}])

    respuesta = cliente.post(_url(nombre, orden), datos, follow=True)

    assert respuesta.redirect_chain[-1][0] == _url("orden_detalle", orden)
    assert "ya está confirmada" in respuesta.content.decode()
    orden.refresh_from_db()
    assert orden.cantidad_consumida == Decimal("40")
    assert orden.derivados.count() == 1


def test_el_destino_se_lista_por_nombre_y_los_campos_tienen_etiqueta(cliente, orden, tunel):
    contenido = cliente.get(_url("orden_detalle", orden)).content.decode()
    assert f'value="{tunel.pk}">Túnel de congelación 1</option>' in contenido
    assert 'aria-label="Cantidad (kg)"' in contenido
    assert 'aria-label="None"' not in contenido
    assert "data-confirmar=" in contenido
