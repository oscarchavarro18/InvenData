"""Administración de maestros del Gerente (RF-02, RF-04 a RF-08, RF-10, RNF-01)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Existencia
from apps.maestros.models import CategoriaProducto, Cliente, Parametro, Proveedor, Ubicacion


@pytest.fixture
def con_gerente(client, gerente):
    client.force_login(gerente)
    return client


def _ultimo(entidad):
    return Auditoria.objects.filter(entidad=entidad).latest("fecha_hora")


# --- Ubicaciones y puntos de venta (RF-05, RF-06) --------------------------------------


def test_el_gerente_abre_un_punto_de_venta_nuevo(con_gerente, gerente):
    respuesta = con_gerente.post(
        reverse("maestros:ubicacion_crear"),
        {"codigo": " pdv-09 ", "nombre": "Punto  Centro", "tipo": "PUNTO_VENTA"},
    )
    assert respuesta.status_code == 302
    punto = Ubicacion.objects.get(codigo="PDV-09")
    assert punto.nombre == "Punto Centro"
    registro = _ultimo("ubicacion")
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.usuario == gerente


def test_no_se_desactiva_una_ubicacion_con_existencia(con_gerente, bodega, lote):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("5"))
    respuesta = con_gerente.post(
        reverse("maestros:ubicacion_estado", args=[bodega.pk]), follow=True
    )
    bodega.refresh_from_db()
    assert bodega.activo
    assert "todavía tiene" in respuesta.content.decode()
    assert not Auditoria.objects.filter(entidad="ubicacion").exists()


def test_no_se_desactiva_un_punto_con_su_administrador_activo(con_gerente, admin_pdv, punto_venta):
    con_gerente.post(reverse("maestros:ubicacion_estado", args=[punto_venta.pk]))
    punto_venta.refresh_from_db()
    assert punto_venta.activo


def test_desactivar_una_ubicacion_vacia_queda_en_auditoria(con_gerente, tunel):
    con_gerente.post(reverse("maestros:ubicacion_estado", args=[tunel.pk]))
    tunel.refresh_from_db()
    assert not tunel.activo
    registro = _ultimo("ubicacion")
    assert registro.valor_anterior["activo"] is True
    assert registro.valor_nuevo["activo"] is False


def test_el_tipo_de_una_ubicacion_con_movimientos_no_cambia(con_gerente, bodega, lote):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("1"))
    con_gerente.post(
        reverse("maestros:ubicacion_editar", args=[bodega.pk]),
        {"codigo": bodega.codigo, "nombre": "Sostenimiento principal", "tipo": "PUNTO_VENTA"},
    )
    bodega.refresh_from_db()
    assert bodega.tipo == "SOSTENIMIENTO"
    assert bodega.nombre == "Sostenimiento principal"


# --- Categorías, productos, clientes, proveedores --------------------------------------


def test_la_categoria_no_se_repite_aunque_cambien_mayusculas(con_gerente, db):
    CategoriaProducto.objects.create(nombre="Pescado")
    respuesta = con_gerente.post(reverse("maestros:categoria_crear"), {"nombre": " pescado "})
    assert respuesta.status_code == 200
    assert "nombre" in respuesta.context["form"].errors
    assert CategoriaProducto.objects.count() == 1


def test_no_se_desactiva_una_categoria_con_productos_activos(con_gerente, producto):
    categoria = producto.categoria
    con_gerente.post(reverse("maestros:categoria_estado", args=[categoria.pk]))
    categoria.refresh_from_db()
    assert categoria.activa


def test_el_gerente_edita_un_producto(con_gerente, producto):
    con_gerente.post(
        reverse("maestros:producto_editar", args=[producto.pk]),
        {
            "codigo": producto.codigo,
            "nombre": "Pechuga sin piel",
            "unidad_medida": "KG",
            "categoria": producto.categoria.pk,
        },
    )
    producto.refresh_from_db()
    assert producto.nombre == "Pechuga sin piel"
    registro = _ultimo("producto")
    assert registro.valor_anterior["nombre"] == "Pechuga"
    assert registro.valor_nuevo["nombre"] == "Pechuga sin piel"


def test_no_se_desactiva_un_producto_con_existencia(con_gerente, producto, lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("3"))
    con_gerente.post(reverse("maestros:producto_estado", args=[producto.pk]))
    producto.refresh_from_db()
    assert producto.activo


def test_un_producto_sin_existencia_se_desactiva(con_gerente, producto):
    con_gerente.post(reverse("maestros:producto_estado", args=[producto.pk]))
    producto.refresh_from_db()
    assert not producto.activo


def test_el_cliente_con_autorizacion_exige_su_fecha(con_gerente, db):
    """RNF-01: la autorización de la Ley 1581 va con la fecha en que se otorgó."""
    datos = {
        "tipo_documento": "NIT",
        "numero_documento": "900 111 222",
        "razon_social": "Restaurante El Muelle",
        "autoriza_tratamiento_datos": "on",
    }
    respuesta = con_gerente.post(reverse("maestros:cliente_crear"), datos)
    assert "fecha_autorizacion" in respuesta.context["form"].errors
    manana = timezone.localdate() + timedelta(days=1)
    respuesta = con_gerente.post(
        reverse("maestros:cliente_crear"), {**datos, "fecha_autorizacion": manana}
    )
    assert "fecha_autorizacion" in respuesta.context["form"].errors
    assert not Cliente.objects.exists()

    hoy = timezone.localdate()
    con_gerente.post(reverse("maestros:cliente_crear"), {**datos, "fecha_autorizacion": hoy})
    cliente = Cliente.objects.get()
    assert cliente.numero_documento == "900111222"
    assert cliente.autoriza_tratamiento_datos


def test_el_proveedor_no_repite_documento(con_gerente, db):
    Proveedor.objects.create(tipo_documento="NIT", numero_documento="900123", razon_social="A")
    respuesta = con_gerente.post(
        reverse("maestros:proveedor_crear"),
        {"tipo_documento": "NIT", "numero_documento": "900123", "razon_social": "B"},
    )
    assert respuesta.status_code == 200
    assert Proveedor.objects.count() == 1


# --- Parámetros ------------------------------------------------------------------------


def test_un_parametro_invalido_no_se_guarda(con_gerente, db):
    parametro, _ = Parametro.objects.update_or_create(
        clave="TOLERANCIA_BALANCE_PCT", defaults={"valor": "5"}
    )
    url = reverse("maestros:parametro_editar", args=[parametro.pk])
    respuesta = con_gerente.post(url, {"valor": "150", "descripcion": "Tolerancia"})
    assert "valor" in respuesta.context["form"].errors
    con_gerente.post(url, {"valor": "3", "descripcion": "Tolerancia"})
    parametro.refresh_from_db()
    assert parametro.valor == "3"
    assert _ultimo("parametro").valor_nuevo["valor"] == "3"


def test_los_parametros_no_se_crean_desde_la_pantalla(con_gerente, db):
    assert con_gerente.get(reverse("maestros:parametro_crear")).status_code == 404


# --- Permisos (RF-02): todo es solo del Gerente ----------------------------------------

RUTAS = [
    ("maestros:administracion", []),
    ("maestros:ubicacion_lista", []),
    ("maestros:ubicacion_crear", []),
    ("maestros:categoria_lista", []),
    ("maestros:cliente_lista", []),
    ("maestros:proveedor_lista", []),
    ("maestros:embalaje_lista", []),
    ("maestros:parametro_lista", []),
]


@pytest.mark.parametrize("perfil", ["jefe_bodega", "admin_pdv", "consulta"])
@pytest.mark.parametrize(("ruta", "args"), RUTAS)
def test_ningun_otro_perfil_entra(client, request, perfil, ruta, args):
    client.force_login(request.getfixturevalue(perfil))
    assert client.get(reverse(ruta, args=args)).status_code == 403


def test_otro_perfil_no_crea_ni_desactiva(client, jefe_bodega, tunel):
    client.force_login(jefe_bodega)
    url = reverse("maestros:ubicacion_crear")
    datos = {"codigo": "X", "nombre": "X", "tipo": "TUNEL_CONGELACION"}
    assert client.post(url, datos).status_code == 403
    assert client.post(reverse("maestros:ubicacion_estado", args=[tunel.pk])).status_code == 403
    tunel.refresh_from_db()
    assert tunel.activo
    assert not Ubicacion.objects.filter(codigo="X").exists()


def test_el_inicio_de_administracion_resume_los_maestros(con_gerente, producto, bodega):
    contenido = con_gerente.get(reverse("maestros:administracion")).content.decode()
    for titulo in ("Usuarios", "Productos", "Ubicaciones y puntos de venta", "Clientes"):
        assert titulo in contenido
    assert reverse("auditoria:auditoria_lista") in contenido


def test_el_menu_de_administracion_es_solo_del_gerente(client, gerente, jefe_bodega):
    client.force_login(gerente)
    nav = client.get(reverse("inicio")).context["nav"]
    assert "Administración" in [g.nombre for g in nav["grupos"]]
    client.force_login(jefe_bodega)
    nav = client.get(reverse("inicio")).context["nav"]
    assert "Administración" not in [g.nombre for g in nav["grupos"]]
    contenido = client.get(reverse("inicio")).content.decode()
    assert reverse("maestros:administracion") not in contenido
