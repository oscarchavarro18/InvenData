"""Lo que se hace en las pantallas de recepción queda en auditoría (RF-10)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Lote
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea, Recepcion
from apps.recepcion.servicios import crear_lote_recepcion, registrar_pesada


@pytest.fixture
def cliente(client, jefe_bodega):
    client.force_login(jefe_bodega)
    return client


def _registros(entidad):
    return list(Auditoria.objects.filter(entidad=entidad).order_by("id"))


def _datos_documento(linea, **cambios):
    datos = {
        "proveedor": linea.documento_proveedor.proveedor.pk,
        "tipo_documento": "REMISION",
        "numero_documento": "R-500",
        "fecha": "2026-10-19",
    }
    datos.update(cambios)
    return datos


def _datos_pesada(canastilla, tunel, **cambios):
    datos = {
        "tipo_embalaje": canastilla.pk,
        "cantidad_embalajes": 10,
        "peso_bruto": "125.00",
        "temperatura": "3.5",
        "ubicacion_destino": tunel.pk,
    }
    datos.update(cambios)
    return datos


# --- Documento --------------------------------------------------------------------


def test_crear_un_documento_deja_su_registro(cliente, linea, jefe_bodega):
    cliente.post(reverse("recepcion:documento_crear"), _datos_documento(linea))
    documento = DocumentoProveedor.objects.get(numero_documento="R-500")
    (registro,) = _registros("documento_proveedor")[-1:]
    assert registro.usuario == jefe_bodega
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.registro_id == documento.pk
    assert registro.valor_anterior is None
    assert registro.valor_nuevo["numero_documento"] == "R-500"
    assert registro.valor_nuevo["estado"] == "ABIERTO"
    assert registro.direccion_ip == "127.0.0.1"


def test_un_documento_repetido_no_deja_registro(cliente, linea):
    cliente.post(reverse("recepcion:documento_crear"), _datos_documento(linea))
    antes = Auditoria.objects.count()
    cliente.post(reverse("recepcion:documento_crear"), _datos_documento(linea))
    assert Auditoria.objects.count() == antes


def test_un_formulario_invalido_no_deja_registro(cliente, linea):
    cliente.post(reverse("recepcion:documento_crear"), _datos_documento(linea, numero_documento=""))
    assert Auditoria.objects.count() == 0


# --- Líneas -----------------------------------------------------------------------


def test_agregar_una_linea_deja_su_registro(cliente, linea, jefe_bodega):
    from apps.maestros.models import CategoriaProducto, Producto

    otro = Producto.objects.create(
        codigo="PES-001",
        nombre="Tilapia",
        unidad_medida="KG",
        categoria=CategoriaProducto.objects.create(nombre="Pescado"),
    )
    cliente.post(
        reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id]),
        {"producto": otro.pk, "cantidad": "40"},
    )
    nueva = DocumentoProveedorLinea.objects.get(producto=otro)
    (registro,) = _registros("documento_proveedor_linea")
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.registro_id == nueva.pk
    assert registro.valor_nuevo["cantidad"] == "40.00"
    assert registro.usuario == jefe_bodega


def test_agregar_un_producto_repetido_no_deja_registro(cliente, linea, producto):
    cliente.post(
        reverse("recepcion:linea_agregar", args=[linea.documento_proveedor_id]),
        {"producto": producto.pk, "cantidad": "40"},
    )
    assert Auditoria.objects.count() == 0


def test_quitar_una_linea_deja_su_registro_con_lo_que_tenia(cliente, linea):
    linea_id = linea.pk
    cliente.post(reverse("recepcion:linea_eliminar", args=[linea_id]))
    assert DocumentoProveedorLinea.objects.count() == 0
    (registro,) = _registros("documento_proveedor_linea")
    assert registro.accion == AccionAuditoria.ANULAR
    assert registro.registro_id == linea_id
    assert registro.valor_anterior["cantidad"] == "100.00"
    assert registro.valor_nuevo is None


def test_quitar_una_linea_con_lotes_no_deja_registro(cliente, linea, lote):
    cliente.post(reverse("recepcion:linea_eliminar", args=[linea.pk]))
    assert DocumentoProveedorLinea.objects.count() == 1
    assert Auditoria.objects.count() == 0


# --- Lotes ------------------------------------------------------------------------


def test_crear_un_lote_deja_su_registro(cliente, linea):
    cliente.post(
        reverse("recepcion:lote_crear", args=[linea.pk]),
        {"estado_producto": "FRESCO", "fecha_vencimiento": "2026-12-05"},
    )
    lote = Lote.objects.get()
    (registro,) = _registros("lote")
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.registro_id == lote.pk
    assert registro.valor_nuevo["estado_producto"] == "FRESCO"
    assert registro.valor_nuevo["fecha_vencimiento"] == "2026-12-05"
    assert registro.valor_nuevo["codigo"] == lote.codigo


def test_un_lote_invalido_no_deja_registro(cliente, linea):
    cliente.post(
        reverse("recepcion:lote_crear", args=[linea.pk]),
        {"estado_producto": "ROTO", "fecha_vencimiento": ""},
    )
    assert Auditoria.objects.count() == 0


def test_eliminar_un_lote_deja_su_registro(cliente, lote):
    lote_id = lote.pk
    cliente.post(reverse("recepcion:lote_eliminar", args=[lote_id]))
    (registro,) = _registros("lote")
    assert registro.accion == AccionAuditoria.ANULAR
    assert registro.registro_id == lote_id
    assert registro.valor_anterior["codigo"] == "L-000001"
    assert registro.valor_nuevo is None


def test_no_eliminar_un_lote_con_pesadas_no_deja_registro(
    cliente, lote, canastilla, tunel, jefe_bodega
):
    registrar_pesada(
        lote=lote,
        tipo_embalaje=canastilla,
        cantidad_embalajes=1,
        peso_bruto=Decimal("30"),
        temperatura=Decimal("2"),
        ubicacion_destino=tunel,
        usuario=jefe_bodega,
    )
    cliente.post(reverse("recepcion:lote_eliminar", args=[lote.pk]))
    assert Auditoria.objects.count() == 0


# --- Pesadas ----------------------------------------------------------------------


def test_registrar_una_pesada_deja_su_registro(cliente, lote, canastilla, tunel, jefe_bodega):
    cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]), _datos_pesada(canastilla, tunel)
    )
    tanda = Recepcion.objects.get()
    (registro,) = _registros("recepcion")
    assert registro.accion == AccionAuditoria.CREAR
    assert registro.registro_id == tanda.pk
    assert registro.usuario == jefe_bodega
    assert registro.valor_nuevo["peso_bruto"] == "125.00"
    assert registro.valor_nuevo["peso_neto"] == "100.00"


def test_una_pesada_invalida_no_deja_registro(cliente, lote, canastilla, tunel):
    cliente.post(
        reverse("recepcion:pesada_registrar", args=[lote.pk]),
        _datos_pesada(canastilla, tunel, peso_bruto="0"),
    )
    assert Auditoria.objects.count() == 0


# --- Todo o nada ------------------------------------------------------------------


def test_si_falla_la_auditoria_no_queda_el_registro_creado(cliente, linea, monkeypatch):
    def falla(**_):
        raise RuntimeError("fallo al escribir la auditoría")

    monkeypatch.setattr("apps.recepcion.views.registrar", falla)
    with pytest.raises(RuntimeError):
        cliente.post(
            reverse("recepcion:lote_crear", args=[linea.pk]),
            {"estado_producto": "FRESCO", "fecha_vencimiento": "2026-12-05"},
        )
    assert Lote.objects.count() == 0


def test_quien_solo_consulta_no_deja_registro(client, linea):
    from apps.accounts.models import Perfil, Usuario

    consulta = Usuario.objects.create_user(
        "consulta",
        "ClaveSegura123",
        nombre_completo="Consulta de prueba",
        perfil=Perfil.objects.get(codigo="CONSULTA"),
    )
    client.force_login(consulta)
    respuesta = client.post(reverse("recepcion:documento_crear"), _datos_documento(linea))
    assert respuesta.status_code == 403
    assert Auditoria.objects.count() == 0


def test_crear_lote_y_pesar_con_el_servicio_no_audita_por_si_solo(
    linea, canastilla, tunel, jefe_bodega
):
    """La auditoría la escribe la pantalla (que conoce a la persona y su IP), no el servicio."""
    lote = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=linea.documento_proveedor.fecha
    )
    registrar_pesada(
        lote=lote,
        tipo_embalaje=canastilla,
        cantidad_embalajes=1,
        peso_bruto=Decimal("30"),
        temperatura=Decimal("2"),
        ubicacion_destino=tunel,
        usuario=jefe_bodega,
    )
    assert Auditoria.objects.count() == 0
