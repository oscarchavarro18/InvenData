"""Permisos por perfil en la recepción (RF-02): leer es de todos, operar es de bodega."""

import pytest
from django.urls import reverse

from apps.accounts.models import Perfil, Usuario
from apps.recepcion.models import DocumentoProveedor


def _usuario(codigo):
    return Usuario.objects.create_user(
        codigo.lower(),
        "ClaveSegura123",
        nombre_completo=f"Usuario {codigo}",
        perfil=Perfil.objects.get(codigo=codigo),
    )


def _detalle(linea):
    return reverse("recepcion:documento_detalle", args=[linea.documento_proveedor_id])


ACCIONES = [
    ("recepcion:documento_crear", False),
    ("recepcion:linea_agregar", True),
    ("recepcion:linea_eliminar", True),
    ("recepcion:lote_crear", True),
    ("recepcion:lote_eliminar", True),
    ("recepcion:pesada_registrar", True),
]


@pytest.mark.parametrize(("nombre", "con_id"), ACCIONES)
def test_un_perfil_sin_permiso_recibe_403_en_cada_accion(client, linea, nombre, con_id):
    client.force_login(_usuario("CONSULTA"))
    url = reverse(nombre, args=[linea.pk]) if con_id else reverse(nombre)
    assert client.post(url, {}).status_code == 403
    assert client.get(url).status_code in (403, 405)


def test_consulta_puede_leer_pero_no_ve_botones_de_accion(client, linea, lote):
    client.force_login(_usuario("CONSULTA"))
    respuesta = client.get(_detalle(linea))
    contenido = respuesta.content.decode()
    assert respuesta.status_code == 200
    assert "L-000001" in contenido
    textos = [
        "Agregar producto",
        "Quitar",
        "Registrar pesada",
        "Nuevo lote",
    ]
    for texto in textos:
        assert texto not in contenido


def test_consulta_no_ve_el_boton_de_nuevo_documento_y_recibe_403_al_entrar(client, linea):
    client.force_login(_usuario("CONSULTA"))
    lista = client.get(reverse("recepcion:documento_lista"))
    assert "Nuevo documento" not in lista.content.decode()
    respuesta = client.get(reverse("recepcion:documento_crear"))
    assert respuesta.status_code == 403
    assert "No tiene permiso" in respuesta.content.decode()


def test_el_gerente_tambien_opera_la_recepcion(client, gerente, linea):
    client.force_login(gerente)
    respuesta = client.post(
        reverse("recepcion:documento_crear"),
        {
            "proveedor": linea.documento_proveedor.proveedor.pk,
            "tipo_documento": "REMISION",
            "numero_documento": "R-9",
            "fecha": "2026-10-02",
        },
    )
    assert respuesta.status_code == 302
    assert DocumentoProveedor.objects.count() == 2


def test_sin_sesion_las_acciones_redirigen_al_ingreso(client, linea):
    respuesta = client.post(reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id]))
    assert respuesta.status_code == 302
    assert respuesta.url.startswith(reverse("login"))
