"""Gestión de usuarios del Gerente (RF-01 a RF-03, RF-10, RNF-04)."""

import pytest
from django.urls import reverse

from apps.accounts import servicios
from apps.accounts.models import Perfil, Usuario
from apps.auditoria.models import AccionAuditoria, Auditoria

CLAVE = "Pescado-Fresco-2026"


@pytest.fixture
def con_gerente(client, gerente):
    client.force_login(gerente)
    return client


def _perfil(codigo):
    return Perfil.objects.get(codigo=codigo).pk


def _datos(**cambios):
    return {
        "usuario": "Maria.Perez",
        "nombre_completo": "María  Pérez",
        "perfil": _perfil("JEFE_BODEGA"),
        "ubicacion": "",
        "clave": CLAVE,
        "confirmacion": CLAVE,
        **cambios,
    }


def test_el_gerente_crea_un_usuario_sin_guardar_la_clave_en_auditoria(con_gerente, gerente):
    respuesta = con_gerente.post(reverse("accounts:usuario_crear"), _datos())
    assert respuesta.status_code == 302
    usuario = Usuario.objects.get(usuario="maria.perez")
    assert usuario.nombre_completo == "María Pérez"
    assert usuario.check_password(CLAVE)
    registro = Auditoria.objects.get(entidad="usuario", registro_id=usuario.pk)
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.usuario == gerente
    assert "password" not in registro.valor_nuevo
    assert CLAVE not in str(registro.valor_nuevo)


def test_el_administrador_de_pdv_exige_su_punto(con_gerente, punto_venta):
    """RF-03: el administrador de PDV queda amarrado a una ubicación de tipo PDV."""
    datos = _datos(perfil=_perfil("ADMIN_PDV"))
    respuesta = con_gerente.post(reverse("accounts:usuario_crear"), datos)
    assert "ubicacion" in respuesta.context["form"].errors
    con_gerente.post(reverse("accounts:usuario_crear"), {**datos, "ubicacion": punto_venta.pk})
    assert Usuario.objects.get(usuario="maria.perez").ubicacion == punto_venta


@pytest.mark.parametrize(
    ("cambios", "campo"),
    [
        ({"confirmacion": "Otra-Clave-2026"}, "confirmacion"),
        ({"clave": "12345", "confirmacion": "12345"}, "clave"),
        ({"usuario": "maria perez"}, "usuario"),
    ],
)
def test_datos_invalidos_no_crean_el_usuario(con_gerente, cambios, campo):
    respuesta = con_gerente.post(reverse("accounts:usuario_crear"), _datos(**cambios))
    assert respuesta.status_code == 200
    assert campo in respuesta.context["form"].errors
    assert not Usuario.objects.filter(nombre_completo="María Pérez").exists()


def test_el_usuario_no_se_repite(con_gerente, jefe_bodega):
    respuesta = con_gerente.post(reverse("accounts:usuario_crear"), _datos(usuario="JEFE"))
    assert "usuario" in respuesta.context["form"].errors


def test_desactivar_a_alguien_le_impide_ingresar(con_gerente, client, jefe_bodega):
    con_gerente.post(reverse("accounts:usuario_estado", args=[jefe_bodega.pk]))
    jefe_bodega.refresh_from_db()
    assert not jefe_bodega.activo
    registro = Auditoria.objects.get(entidad="usuario", registro_id=jefe_bodega.pk)
    assert registro.valor_nuevo["activo"] is False
    client.logout()
    assert not client.login(username="jefe", password="ClaveSegura123")


def test_nadie_se_desactiva_a_si_mismo(con_gerente, gerente):
    respuesta = con_gerente.post(reverse("accounts:usuario_estado", args=[gerente.pk]), follow=True)
    gerente.refresh_from_db()
    assert gerente.activo
    assert "No puede desactivar su propio usuario." in respuesta.content.decode()


def test_siempre_queda_un_gerente_activo(gerente, consulta):
    with pytest.raises(servicios.UsuarioInvalido, match="al menos un Gerente"):
        servicios.cambiar_estado_usuario(usuario=gerente, actor=consulta)
    gerente.refresh_from_db()
    assert gerente.activo


def test_el_gerente_no_se_quita_su_propio_perfil(con_gerente, gerente):
    respuesta = con_gerente.post(
        reverse("accounts:usuario_editar", args=[gerente.pk]),
        {"nombre_completo": gerente.nombre_completo, "perfil": _perfil("CONSULTA")},
    )
    assert respuesta.status_code == 200
    assert "No puede quitarse a sí mismo" in respuesta.content.decode()
    gerente.refresh_from_db()
    assert gerente.es_gerente


def test_cambiar_la_clave_no_deja_el_hash_en_auditoria(con_gerente, jefe_bodega):
    url = reverse("accounts:usuario_clave", args=[jefe_bodega.pk])
    con_gerente.post(url, {"clave": CLAVE, "confirmacion": CLAVE})
    jefe_bodega.refresh_from_db()
    assert jefe_bodega.check_password(CLAVE)
    registro = Auditoria.objects.get(entidad="usuario", registro_id=jefe_bodega.pk)
    assert "pbkdf2" not in str(registro.valor_nuevo)
    assert registro.valor_nuevo == {"contraseña": "restablecida por el Gerente"}


@pytest.mark.parametrize("perfil", ["jefe_bodega", "admin_pdv", "consulta"])
def test_solo_el_gerente_gestiona_usuarios(client, request, perfil, jefe_bodega):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(reverse("accounts:usuario_lista")).status_code == 403
    assert client.post(reverse("accounts:usuario_crear"), _datos()).status_code == 403
    url = reverse("accounts:usuario_estado", args=[jefe_bodega.pk])
    assert client.post(url).status_code == 403


def test_la_lista_filtra_por_perfil(con_gerente, jefe_bodega, consulta):
    contenido = con_gerente.get(
        reverse("accounts:usuario_lista"), {"perfil": "JEFE_BODEGA"}
    ).content.decode()
    assert "Jefe de prueba" in contenido
    assert "Consulta de prueba" not in contenido
