"""Consulta de la auditoría en la Administración (RF-10, RNF-07)."""

import pytest
from django.urls import reverse

from apps.auditoria import consultas
from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import registrar


@pytest.fixture
def con_gerente(client, gerente):
    client.force_login(gerente)
    return client


@pytest.fixture
def cambio_de_tara(gerente):
    return registrar(
        usuario=gerente,
        entidad="tipo_embalaje",
        registro_id=7,
        accion=AccionAuditoria.MODIFICAR,
        valor_anterior={"nombre": "Canastilla", "peso_tara": "2.50", "activo": True},
        valor_nuevo={"nombre": "Canastilla", "peso_tara": "2.75", "activo": True},
        ip="10.0.0.5",
    )


def test_cambios_marca_lo_que_cambio_primero(cambio_de_tara):
    filas = consultas.cambios(cambio_de_tara)
    assert filas[0]["cambio"] is True
    assert (filas[0]["antes"], filas[0]["despues"]) == ("2.50", "2.75")
    assert [f["cambio"] for f in filas[1:]] == [False, False]
    assert "2.50 > 2.75" in consultas.resumen_de_cambios(cambio_de_tara)


def test_el_nombre_del_modulo_es_legible():
    assert consultas.nombre_de_entidad("tipo_embalaje") == "Tipo de embalaje"


def test_la_lista_muestra_y_filtra(con_gerente, cambio_de_tara, gerente):
    registrar(
        usuario=gerente,
        entidad="producto",
        registro_id=1,
        accion=AccionAuditoria.CREAR,
        valor_nuevo={"nombre": "Tilapia"},
    )
    contenido = con_gerente.get(reverse("auditoria:auditoria_lista")).content.decode()
    assert "Tipo de embalaje" in contenido
    assert "Registro nuevo" in contenido
    filtrado = con_gerente.get(
        reverse("auditoria:auditoria_lista"), {"entidad": "producto"}
    ).content.decode()
    assert "Registro nuevo" in filtrado
    assert "2.50 &gt; 2.75" not in filtrado


def test_el_detalle_muestra_antes_y_despues(con_gerente, cambio_de_tara):
    contenido = con_gerente.get(
        reverse("auditoria:auditoria_detalle", args=[cambio_de_tara.pk])
    ).content.decode()
    assert "Qué cambió" in contenido
    assert "fila--cambio" in contenido
    assert "10.0.0.5" in contenido


def test_se_exporta_a_csv_y_pdf(con_gerente, cambio_de_tara):
    url = reverse("auditoria:auditoria_lista")
    csv = con_gerente.get(url, {"formato": "csv"})
    assert "Auditoría de operaciones" in csv.content.decode("utf-8")
    pdf = con_gerente.get(url, {"formato": "pdf"})
    assert pdf.content.startswith(b"%PDF")


@pytest.mark.parametrize("perfil", ["jefe_bodega", "admin_pdv", "consulta"])
def test_solo_el_gerente_consulta_la_auditoria(client, request, perfil, cambio_de_tara):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(reverse("auditoria:auditoria_lista")).status_code == 403
    url = reverse("auditoria:auditoria_detalle", args=[cambio_de_tara.pk])
    assert client.get(url).status_code == 403
