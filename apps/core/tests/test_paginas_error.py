"""Páginas de error propias, en español y con la marca (no las genéricas de Django)."""

from django.template.loader import render_to_string


def test_la_pagina_404_es_propia(client, gerente):
    client.force_login(gerente)
    respuesta = client.get("/esta-direccion-no-existe/")
    contenido = respuesta.content.decode()
    assert respuesta.status_code == 404
    assert "Esta página no existe" in contenido
    assert "Not Found" not in contenido


def test_la_pagina_404_sin_sesion_tambien_es_propia(client, db):
    respuesta = client.get("/esta-direccion-no-existe/")
    assert "Esta página no existe" in respuesta.content.decode()


def test_la_pagina_500_no_depende_de_la_sesion_ni_del_menu():
    """Se dibuja sin request ni contexto, como lo hace Django ante un error grave."""
    html = render_to_string("500.html")
    assert "Algo falló en el sistema" in html
    assert 'class="menu"' not in html
