from decimal import Decimal

import pytest
from django.urls import reverse

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Existencia
from apps.maestros.models import CategoriaProducto, Parametro, Producto, TipoEmbalaje


@pytest.fixture
def con_sesion(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


@pytest.fixture
def con_gerente(client, gerente):
    client.force_login(gerente)
    return client


@pytest.mark.parametrize("nombre", ["producto_lista", "producto_crear", "configuracion"])
def test_las_pantallas_exigen_sesion(client, db, nombre):
    respuesta = client.get(reverse(f"maestros:{nombre}"))
    assert respuesta.status_code == 302
    assert "/login/" in respuesta["Location"]


def test_lista_productos_con_su_existencia(con_sesion, producto, lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("42.5"))
    respuesta = con_sesion.get(reverse("maestros:producto_lista"))
    contenido = respuesta.content.decode()
    assert "POL-001" in contenido
    assert "Pechuga" in contenido
    assert "42,50 kg" in contenido


def test_un_producto_sin_lotes_muestra_cero(con_sesion, producto):
    contenido = con_sesion.get(reverse("maestros:producto_lista")).content.decode()
    assert "0,00 kg" in contenido


def test_la_existencia_de_un_producto_no_se_duplica_con_varios_lotes(
    con_sesion, producto, lote, datos_lote, bodega, tunel
):
    from apps.inventario.models import Lote

    otro = Lote.objects.create(codigo="L-000002", origen="INVENTARIO_INICIAL", **datos_lote)
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("10"))
    Existencia.objects.create(lote=lote, ubicacion=tunel, cantidad=Decimal("5"))
    Existencia.objects.create(lote=otro, ubicacion=bodega, cantidad=Decimal("2"))
    respuesta = con_sesion.get(reverse("maestros:producto_lista"))
    (fila,) = respuesta.context["pagina"]
    assert fila.existencia == Decimal("17")


def test_busca_productos(con_sesion, producto):
    categoria = CategoriaProducto.objects.create(nombre="Pescado")
    Producto.objects.create(
        codigo="TIL-001", nombre="Tilapia", unidad_medida="KG", categoria=categoria
    )

    por_nombre = con_sesion.get(reverse("maestros:producto_lista"), {"q": "tilap"})
    assert [p.codigo for p in por_nombre.context["pagina"]] == ["TIL-001"]

    por_categoria = con_sesion.get(reverse("maestros:producto_lista"), {"q": "pollo"})
    assert [p.codigo for p in por_categoria.context["pagina"]] == ["POL-001"]

    ninguno = con_sesion.get(reverse("maestros:producto_lista"), {"q": "zzz"})
    assert "Ningún producto coincide" in ninguno.content.decode()


def test_pagina_los_productos_y_conserva_la_busqueda(con_sesion, db):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    for numero in range(25):
        Producto.objects.create(
            codigo=f"P-{numero:03d}",
            nombre=f"Pollo {numero}",
            unidad_medida="KG",
            categoria=categoria,
        )
    respuesta = con_sesion.get(reverse("maestros:producto_lista"), {"q": "pollo"})
    assert len(respuesta.context["pagina"]) == 20
    assert "q=pollo&amp;pagina=2" in respuesta.content.decode()
    segunda = con_sesion.get(reverse("maestros:producto_lista"), {"q": "pollo", "pagina": 2})
    assert len(segunda.context["pagina"]) == 5


def test_solo_el_gerente_ve_el_boton_nuevo_producto(con_sesion, con_gerente):
    url = reverse("maestros:producto_lista")
    assert "Nuevo producto" in con_gerente.get(url).content.decode()
    con_sesion.logout()
    assert "Nuevo producto" not in con_sesion.get(url).content.decode()


def test_el_gerente_crea_un_producto(con_gerente, db):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    respuesta = con_gerente.post(
        reverse("maestros:producto_crear"),
        {
            "codigo": " alas-01 ",
            "nombre": "Alitas",
            "presentacion": "Bolsa x 1 kg",
            "unidad_medida": "KG",
            "categoria": categoria.pk,
            "admite_transformacion": "on",
        },
    )
    assert respuesta.status_code == 302
    producto = Producto.objects.get(codigo="ALAS-01")
    assert producto.nombre == "Alitas"
    assert producto.admite_transformacion
    assert producto.activo


def test_crear_un_producto_deja_su_registro_de_auditoria(con_gerente, gerente, db):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    con_gerente.post(
        reverse("maestros:producto_crear"),
        {
            "codigo": "alas-01",
            "nombre": "Alitas",
            "presentacion": "Bolsa x 1 kg",
            "unidad_medida": "KG",
            "categoria": categoria.pk,
        },
    )
    producto = Producto.objects.get(codigo="ALAS-01")
    registro = Auditoria.objects.get(entidad="producto", registro_id=producto.pk)
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.usuario == gerente
    assert registro.valor_anterior is None
    assert registro.valor_nuevo["codigo"] == "ALAS-01"


def test_un_producto_invalido_no_deja_registro_de_auditoria(con_gerente, producto):
    con_gerente.post(
        reverse("maestros:producto_crear"),
        {"codigo": producto.codigo, "nombre": "Otro", "unidad_medida": "KG"},
    )
    assert not Auditoria.objects.filter(entidad="producto").exists()


def test_no_crea_un_producto_con_codigo_repetido(con_gerente, producto):
    respuesta = con_gerente.post(
        reverse("maestros:producto_crear"),
        {
            "codigo": "pol-001",
            "nombre": "Otro",
            "unidad_medida": "KG",
            "categoria": producto.categoria.pk,
        },
    )
    assert respuesta.status_code == 200
    assert Producto.objects.count() == 1
    assert respuesta.context["form"].errors["codigo"]


def test_el_formulario_valida_los_campos_obligatorios(con_gerente, db):
    respuesta = con_gerente.post(reverse("maestros:producto_crear"), {})
    assert respuesta.status_code == 200
    assert {"codigo", "nombre", "unidad_medida", "categoria"} <= set(
        respuesta.context["form"].errors
    )


def test_el_formulario_solo_ofrece_categorias_activas(con_gerente, db):
    CategoriaProducto.objects.create(nombre="Activa")
    CategoriaProducto.objects.create(nombre="Vieja", activa=False)
    respuesta = con_gerente.get(reverse("maestros:producto_crear"))
    nombres = [c.nombre for c in respuesta.context["form"].fields["categoria"].queryset]
    assert nombres == ["Activa"]


def test_otro_perfil_no_puede_crear_productos(con_sesion, db):
    url = reverse("maestros:producto_crear")
    assert con_sesion.get(url).status_code == 403
    assert con_sesion.post(url, {"codigo": "X", "nombre": "X"}).status_code == 403
    assert Producto.objects.count() == 0


def test_configuracion_muestra_los_catalogos(con_sesion, bodega):
    TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("2.50"))
    Parametro.objects.create(clave="TOLERANCIA", valor="2", descripcion="Tolerancia de balance")
    contenido = con_sesion.get(reverse("maestros:configuracion")).content.decode()
    assert "Cuarto de sostenimiento" in contenido
    assert "Canastilla" in contenido
    assert "TOLERANCIA" in contenido
    assert "/admin/" not in contenido  # el enlace al panel es solo del gerente


def test_configuracion_ofrece_el_panel_al_gerente(con_gerente):
    contenido = con_gerente.get(reverse("maestros:configuracion")).content.decode()
    assert "/admin/" in contenido
