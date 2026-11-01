"""Pantallas, descargas y alcance por perfil de los reportes (RF-02, RF-66, RN-06, RN-07)."""

import pytest
from django.urls import reverse

from apps.accounts.models import Perfil, Usuario

REPORTES_BODEGA = ("reportes:existencias_bodega", "reportes:por_vencer")
REPORTES_PDV = ("reportes:existencias_pdv", "reportes:ventas")
TODOS = (*REPORTES_BODEGA, *REPORTES_PDV, "reportes:correcciones")


@pytest.fixture
def admin_otro(otro_punto):
    """Administrador del punto 2."""
    return Usuario.objects.create_user(
        "admin_otro",
        "ClaveSegura123",
        nombre_completo="Administrador del punto 2",
        perfil=Perfil.objects.get(codigo="ADMIN_PDV"),
        ubicacion=otro_punto,
    )


def _entrar(client, usuario):
    client.force_login(usuario)
    return client


def test_sin_sesion_va_al_ingreso(client):
    for ruta in ("reportes:indice", *TODOS):
        respuesta = client.get(reverse(ruta))
        assert respuesta.status_code == 302
        assert "/login/" in respuesta["Location"]


@pytest.mark.parametrize("ruta", TODOS)
def test_gerente_ve_todos_los_reportes(client, gerente, ruta):
    respuesta = _entrar(client, gerente).get(reverse(ruta))
    assert respuesta.status_code == 200
    assert b"Descargar CSV" in respuesta.content


@pytest.mark.parametrize("ruta", TODOS)
def test_consulta_ve_todos_los_reportes(client, consulta, ruta):
    """RN-07: el perfil de consulta lee todo."""
    assert _entrar(client, consulta).get(reverse(ruta)).status_code == 200


def test_indice_segun_perfil(client, gerente, jefe_bodega, admin_pdv):
    contenido = _entrar(client, gerente).get(reverse("reportes:indice")).content.decode()
    for ruta in TODOS:
        assert f'href="{reverse(ruta)}"' in contenido

    contenido = _entrar(client, jefe_bodega).get(reverse("reportes:indice")).content.decode()
    assert f'href="{reverse("reportes:existencias_bodega")}"' in contenido
    assert f'href="{reverse("reportes:ventas")}"' not in contenido

    contenido = _entrar(client, admin_pdv).get(reverse("reportes:indice")).content.decode()
    assert f'href="{reverse("reportes:ventas")}"' in contenido
    assert f'href="{reverse("reportes:existencias_bodega")}"' not in contenido
    assert f'href="{reverse("reportes:por_vencer")}"' not in contenido


def test_menu_lleva_a_reportes(client, admin_pdv):
    contenido = _entrar(client, admin_pdv).get(reverse("reportes:indice")).content.decode()
    assert f'href="{reverse("reportes:indice")}"' in contenido
    assert "menu__pronto" not in contenido


@pytest.mark.parametrize("ruta", REPORTES_BODEGA)
@pytest.mark.parametrize("formato", ["", "csv", "pdf"])
def test_admin_pdv_no_ve_reportes_de_bodega(client, admin_pdv, ruta, formato):
    """RN-06: ni en pantalla ni descargado."""
    respuesta = _entrar(client, admin_pdv).get(reverse(ruta), {"formato": formato})
    assert respuesta.status_code == 403


@pytest.mark.parametrize("ruta", REPORTES_PDV)
def test_jefe_de_bodega_no_ve_reportes_de_pdv(client, jefe_bodega, ruta):
    assert _entrar(client, jefe_bodega).get(reverse(ruta)).status_code == 403


def test_admin_pdv_solo_ve_su_punto(client, admin_pdv, con_ventas, otro_punto):
    """RN-07: aunque pida otro punto en la URL, el reporte sale solo con el suyo."""
    respuesta = _entrar(client, admin_pdv).get(
        reverse("reportes:ventas"), {"ubicacion": otro_punto.pk, "formato": "csv"}
    )
    texto = respuesta.content.decode("utf-8")
    assert "Punto de venta 1" in texto
    assert "Punto de venta 2" not in texto
    # Sus 17 kg en una factura y una remisión, sin los 3 kg del otro punto.
    assert "Total;;;2;17,00;100,0 %" in texto


def test_admin_pdv_no_ve_ajustes_de_bodega(client, admin_pdv, con_ajustes):
    contenido = _entrar(client, admin_pdv).get(reverse("reportes:correcciones")).content.decode()
    assert "Conteo de cierre" in contenido
    assert "Canastilla rota" not in contenido
    assert 'name="ambito"' not in contenido


def test_jefe_ve_solo_ajustes_de_bodega(client, jefe_bodega, con_ajustes):
    contenido = _entrar(client, jefe_bodega).get(reverse("reportes:correcciones")).content.decode()
    assert "Canastilla rota" in contenido
    assert "Conteo de cierre" not in contenido


def test_otro_admin_no_ve_ventas_ajenas(client, admin_otro, con_ventas):
    respuesta = _entrar(client, admin_otro).get(reverse("reportes:ventas"), {"formato": "csv"})
    texto = respuesta.content.decode("utf-8")
    assert "Total;;;1;3,00;100,0 %" in texto


def test_descargas_csv_y_pdf(client, gerente, en_bodega):
    _entrar(client, gerente)
    csv = client.get(reverse("reportes:existencias_bodega"), {"formato": "csv"})
    assert csv["Content-Type"].startswith("text/csv")
    assert "L-000001" in csv.content.decode("utf-8")
    pdf = client.get(reverse("reportes:existencias_bodega"), {"formato": "pdf"})
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_enlaces_de_descarga_conservan_los_filtros(client, gerente, en_bodega, bodega):
    contenido = (
        _entrar(client, gerente)
        .get(reverse("reportes:existencias_bodega"), {"ubicacion": bodega.pk})
        .content.decode()
    )
    assert f"ubicacion={bodega.pk}&amp;formato=csv" in contenido
    assert f"ubicacion={bodega.pk}&amp;formato=pdf" in contenido


def test_filtro_de_ubicacion_en_pantalla(client, gerente, en_bodega, vencido, tunel):
    contenido = (
        _entrar(client, gerente)
        .get(reverse("reportes:existencias_bodega"), {"ubicacion": tunel.pk})
        .content.decode()
    )
    assert "L-000099" in contenido
    assert "L-000001" not in contenido


def test_fechas_invertidas_muestran_error(client, gerente, con_ventas):
    """Un periodo imposible no rompe el reporte: avisa y usa el periodo por defecto."""
    respuesta = _entrar(client, gerente).get(
        reverse("reportes:ventas"), {"desde": "2026-10-31", "hasta": "2026-10-01"}
    )
    assert respuesta.status_code == 200
    assert "La fecha inicial no puede ser posterior a la final." in respuesta.content.decode()
    assert respuesta.context["reporte"].totales["kg"] == 20


def test_dias_fuera_de_rango_usan_el_valor_por_defecto(client, gerente, vencido):
    respuesta = _entrar(client, gerente).get(reverse("reportes:por_vencer"), {"dias": "999"})
    assert respuesta.status_code == 200
    assert "Vencidos y los que vencen en 7 días o menos" in respuesta.content.decode()
