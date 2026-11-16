"""Interfaz FishPID: navegación por perfil, cadena del día y pendientes (RF-02, RN-06)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.consultas import cadena_del_dia, pendientes
from apps.despacho.models import TrasladoPdv


def _nav(client, usuario):
    client.force_login(usuario)
    return client.get(reverse("inicio")).context["nav"]


def _nombres(items):
    return [item.nombre for item in items]


@pytest.fixture
def traslado(bodega, punto_venta, jefe_bodega):
    """Un traslado enviado que espera la verificación del punto de venta."""
    return TrasladoPdv.objects.create(
        consecutivo="T-000001",
        fecha=timezone.localdate(),
        ubicacion_origen=bodega,
        ubicacion_destino=punto_venta,
        usuario_responsable=jefe_bodega,
        nombre_entrega="Luis Gómez",
    )


def test_el_jefe_de_bodega_ve_bodega_y_salidas_pero_no_los_pdv(client, jefe_bodega):
    nav = _nav(client, jefe_bodega)
    assert [g.nombre for g in nav["grupos"]] == ["Bodega", "Salidas", "Control"]
    assert "Recepción" in _nombres(nav["acciones"])
    assert "Venta" not in _nombres(nav["acciones"])


def test_el_admin_pdv_no_ve_la_bodega_en_ninguna_parte(client, admin_pdv):
    """RN-06: ni en el menú, ni en la barra inferior, ni en el buscador."""
    nav = _nav(client, admin_pdv)
    assert "Bodega" not in [g.nombre for g in nav["grupos"]]
    assert "Inventario" not in _nombres(nav["buscables"])
    assert _nombres(nav["barra"]) == ["Existencia PDV", "Ventas"]
    assert {"Venta", "Remisión", "Conteo físico"} <= set(_nombres(nav["acciones"]))
    assert "Recepción" not in _nombres(nav["acciones"])


def test_consulta_no_tiene_nada_que_registrar(client, consulta):
    """RN-07: solo lectura, así que no aparece el botón «Registrar»."""
    client.force_login(consulta)
    respuesta = client.get(reverse("inicio"))
    assert respuesta.context["nav"]["acciones"] == []
    assert 'data-abrir-hoja="hoja-registrar"' not in respuesta.content.decode()


def test_un_solo_modulo_activo_y_su_grupo_resaltado(client, jefe_bodega):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("recepcion:documento_lista")).content.decode()
    assert contenido.count("menu__item--activo") == 1
    assert "menu__grupo--actual" in contenido
    assert "barra-inf" in contenido


def test_la_cadena_tiene_las_seis_etapas_y_avisa_los_traslados(traslado):
    cadena = cadena_del_dia()
    assert [e["nombre"] for e in cadena] == [
        "Recepción",
        "Almacén",
        "Transformación",
        "Embultaje",
        "Traslados a PDV",
        "Despacho",
    ]
    traslados = cadena[4]
    assert traslados["alerta"] is True
    assert traslados["nota"] == "1 por verificar"


def test_pendientes_con_la_accion_segun_el_perfil(linea, traslado, gerente, jefe_bodega, consulta):
    """Quien puede hacerlo ve la acción; quien no, solo «Ver»."""
    del_jefe, total = pendientes(jefe_bodega)
    assert total == 2
    acciones = {p["etapa"]: p["accion"] for p in del_jefe}
    assert acciones == {"recepcion": "Revisar y cerrar", "traslados": "Ver"}

    del_gerente, _ = pendientes(gerente)
    assert {p["etapa"]: p["accion"] for p in del_gerente}["traslados"] == "Verificar"

    de_consulta, _ = pendientes(consulta)
    assert {p["accion"] for p in de_consulta} == {"Ver"}


def test_el_inicio_muestra_la_cadena_y_los_pendientes(client, jefe_bodega, linea):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("inicio")).content.decode()
    assert "Cadena del día" in contenido
    assert "Cerrar la recepción FACTURA F-100" in contenido
    assert reverse("recepcion:documento_detalle", args=[linea.documento_proveedor.pk]) in contenido


def test_el_admin_pdv_no_ve_la_cadena(client, admin_pdv, traslado):
    client.force_login(admin_pdv)
    contenido = client.get(reverse("inicio")).content.decode()
    assert "Cadena del día" not in contenido
    assert "Verificar el traslado T-000001" in contenido


def test_el_ingreso_lleva_el_logo_animado(client, db):
    contenido = client.get(reverse("login")).content.decode()
    assert 'class="orbe"' in contenido
    assert "img/logo-fishpid.png" in contenido
    assert "data-ver-clave" in contenido
