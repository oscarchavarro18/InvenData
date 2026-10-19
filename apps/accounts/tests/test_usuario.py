import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Perfil, Usuario


def test_existen_los_cuatro_perfiles(db):
    assert set(Perfil.objects.values_list("codigo", flat=True)) == {
        "GERENTE",
        "JEFE_BODEGA",
        "ADMIN_PDV",
        "CONSULTA",
    }


def test_superusuario_es_gerente_con_control_total(gerente):
    assert gerente.perfil.codigo == "GERENTE"
    assert gerente.is_staff and gerente.is_superuser
    assert gerente.has_perm("cualquier.permiso")


def test_contrasena_se_guarda_con_hash(gerente):
    assert gerente.password != "ClaveSegura123"
    assert gerente.check_password("ClaveSegura123")


def test_jefe_de_bodega_no_tiene_privilegios_de_gerente(jefe_bodega):
    assert not jefe_bodega.is_staff
    assert not jefe_bodega.has_perm("cualquier.permiso")


def test_admin_pdv_requiere_punto_de_venta(db, bodega):
    perfil = Perfil.objects.get(codigo="ADMIN_PDV")
    sin_ubicacion = Usuario(usuario="pdv", nombre_completo="Admin PDV", perfil=perfil)
    with pytest.raises(ValidationError):
        sin_ubicacion.full_clean(exclude=["password"])
    en_bodega = Usuario(usuario="pdv", nombre_completo="Admin PDV", perfil=perfil, ubicacion=bodega)
    with pytest.raises(ValidationError):
        en_bodega.full_clean(exclude=["password"])


def test_admin_pdv_con_punto_de_venta_es_valido(db, punto_venta):
    perfil = Perfil.objects.get(codigo="ADMIN_PDV")
    usuario = Usuario(
        usuario="pdv", nombre_completo="Admin PDV", perfil=perfil, ubicacion=punto_venta
    )
    usuario.full_clean(exclude=["password"])


def test_otros_perfiles_no_llevan_ubicacion(db, punto_venta):
    perfil = Perfil.objects.get(codigo="JEFE_BODEGA")
    usuario = Usuario(usuario="jefe", nombre_completo="Jefe", perfil=perfil, ubicacion=punto_venta)
    with pytest.raises(ValidationError):
        usuario.full_clean(exclude=["password"])


def test_usuario_inactivo_no_puede_iniciar_sesion(client, gerente):
    gerente.activo = False
    gerente.save()
    assert not client.login(username="gerente", password="ClaveSegura123")


def test_login_y_pagina_de_inicio(client, gerente):
    assert client.login(username="gerente", password="ClaveSegura123")
    respuesta = client.get("/")
    assert respuesta.status_code == 200
    assert "Dashboard" in respuesta.content.decode()


def test_admin_solo_para_gerente(client, gerente, jefe_bodega):
    client.force_login(jefe_bodega)
    assert client.get("/admin/").status_code == 302
    client.force_login(gerente)
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/accounts/usuario/").status_code == 200
    assert client.get("/admin/accounts/usuario/add/").status_code == 200


def test_la_pantalla_de_ingreso_muestra_los_campos_con_estilo(client, db):
    respuesta = client.get("/login/")
    contenido = respuesta.content.decode()
    assert respuesta.status_code == 200
    assert 'class="form-control"' in contenido
    assert "Ingresar" in contenido
    assert 'class="menu"' not in contenido  # sin menú lateral antes de iniciar sesión


def test_el_ingreso_conserva_la_pagina_pedida(client, gerente):
    respuesta = client.post(
        "/login/",
        {"username": "gerente", "password": "ClaveSegura123", "next": "/recepcion/"},
    )
    assert respuesta.status_code == 302
    assert respuesta["Location"] == "/recepcion/"
