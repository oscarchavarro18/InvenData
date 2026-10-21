"""Los tipos de embalaje se administran desde Configuración, solo por la gerencia (RF-08, RF-10)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.maestros.models import TipoEmbalaje
from apps.recepcion.forms import TandaForm


@pytest.fixture
def con_gerente(client, gerente):
    client.force_login(gerente)
    return client


@pytest.fixture
def con_jefe(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def canastilla(db):
    return TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("2.50"))


def _registros(embalaje):
    return list(Auditoria.objects.filter(entidad="tipo_embalaje", registro_id=embalaje.pk))


# --- Crear -------------------------------------------------------------------------


def test_el_gerente_crea_un_tipo_de_embalaje_y_queda_en_auditoria(con_gerente, gerente, db):
    respuesta = con_gerente.post(
        reverse("maestros:embalaje_crear"), {"nombre": "  Caja   grande ", "peso_tara": "1.20"}
    )
    assert respuesta.status_code == 302
    embalaje = TipoEmbalaje.objects.get(nombre="Caja grande")
    assert embalaje.peso_tara == Decimal("1.20")
    assert embalaje.activo
    (registro,) = _registros(embalaje)
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.usuario == gerente
    assert registro.valor_anterior is None
    assert registro.valor_nuevo["peso_tara"] == "1.20"


def test_se_puede_crear_un_embalaje_con_tara_cero(con_gerente, db):
    con_gerente.post(
        reverse("maestros:embalaje_crear"), {"nombre": "Sin embalaje", "peso_tara": "0"}
    )
    assert TipoEmbalaje.objects.get(nombre="Sin embalaje").peso_tara == 0


@pytest.mark.parametrize(
    "datos, campo",
    [
        ({"nombre": "", "peso_tara": "1"}, "nombre"),
        ({"nombre": "Caja", "peso_tara": ""}, "peso_tara"),
        ({"nombre": "Caja", "peso_tara": "-1"}, "peso_tara"),
    ],
)
def test_un_embalaje_invalido_no_se_crea_ni_deja_registro(con_gerente, db, datos, campo):
    respuesta = con_gerente.post(reverse("maestros:embalaje_crear"), datos)
    assert respuesta.status_code == 200
    assert campo in respuesta.context["form"].errors
    assert not TipoEmbalaje.objects.exists()
    assert not Auditoria.objects.filter(entidad="tipo_embalaje").exists()


def test_no_se_repite_el_nombre_aunque_cambien_mayusculas(con_gerente, canastilla):
    respuesta = con_gerente.post(
        reverse("maestros:embalaje_crear"), {"nombre": "canastilla", "peso_tara": "3"}
    )
    assert respuesta.status_code == 200
    assert "nombre" in respuesta.context["form"].errors
    assert TipoEmbalaje.objects.count() == 1


# --- Editar ------------------------------------------------------------------------


def test_cambiar_la_tara_deja_el_valor_anterior_y_el_nuevo(con_gerente, canastilla):
    url = reverse("maestros:embalaje_editar", args=[canastilla.pk])
    respuesta = con_gerente.post(url, {"nombre": "Canastilla", "peso_tara": "2.75"})
    assert respuesta.status_code == 302
    canastilla.refresh_from_db()
    assert canastilla.peso_tara == Decimal("2.75")
    (registro,) = _registros(canastilla)
    assert registro.accion == AccionAuditoria.MODIFICAR
    assert registro.valor_anterior["peso_tara"] == "2.50"
    assert registro.valor_nuevo["peso_tara"] == "2.75"


def test_editar_un_embalaje_sin_cambiar_su_propio_nombre_es_valido(con_gerente, canastilla):
    url = reverse("maestros:embalaje_editar", args=[canastilla.pk])
    assert con_gerente.post(url, {"nombre": "Canastilla", "peso_tara": "3"}).status_code == 302


def test_editar_un_embalaje_inexistente_da_404(con_gerente, db):
    assert con_gerente.get(reverse("maestros:embalaje_editar", args=[999])).status_code == 404


# --- Activar y desactivar ----------------------------------------------------------


def test_desactivar_lo_saca_de_las_pesadas_y_queda_en_auditoria(con_gerente, canastilla):
    url = reverse("maestros:embalaje_estado", args=[canastilla.pk])
    assert con_gerente.post(url).status_code == 302
    canastilla.refresh_from_db()
    assert not canastilla.activo
    assert canastilla not in TandaForm().fields["tipo_embalaje"].queryset
    (registro,) = _registros(canastilla)
    assert registro.valor_anterior["activo"] is True
    assert registro.valor_nuevo["activo"] is False


def test_reactivar_lo_vuelve_a_ofrecer_en_las_pesadas(con_gerente, canastilla):
    canastilla.activo = False
    canastilla.save()
    con_gerente.post(reverse("maestros:embalaje_estado", args=[canastilla.pk]))
    canastilla.refresh_from_db()
    assert canastilla.activo
    assert canastilla in TandaForm().fields["tipo_embalaje"].queryset


def test_cambiar_el_estado_exige_post(con_gerente, canastilla):
    respuesta = con_gerente.get(reverse("maestros:embalaje_estado", args=[canastilla.pk]))
    assert respuesta.status_code == 405
    canastilla.refresh_from_db()
    assert canastilla.activo


# --- Permisos ----------------------------------------------------------------------


def test_otro_perfil_no_administra_embalajes(con_jefe, canastilla):
    for nombre, args in [
        ("embalaje_crear", []),
        ("embalaje_editar", [canastilla.pk]),
        ("embalaje_estado", [canastilla.pk]),
    ]:
        url = reverse(f"maestros:{nombre}", args=args)
        assert con_jefe.post(url, {"nombre": "X", "peso_tara": "1"}).status_code == 403
    canastilla.refresh_from_db()
    assert canastilla.activo
    assert canastilla.peso_tara == Decimal("2.50")
    assert not Auditoria.objects.filter(entidad="tipo_embalaje").exists()


def test_sin_sesion_se_pide_iniciar_sesion(client, canastilla):
    respuesta = client.get(reverse("maestros:embalaje_crear"))
    assert respuesta.status_code == 302
    assert "/login/" in respuesta["Location"]


def test_solo_el_gerente_ve_los_botones_de_administrar(client, gerente, jefe_bodega, canastilla):
    url = reverse("maestros:configuracion")
    client.force_login(gerente)
    contenido = client.get(url).content.decode()
    assert "Nuevo tipo" in contenido
    assert "Desactivar" in contenido
    client.force_login(jefe_bodega)
    contenido = client.get(url).content.decode()
    assert "Nuevo tipo" not in contenido
    assert "Desactivar" not in contenido
