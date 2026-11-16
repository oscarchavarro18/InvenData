"""Levantamiento de inventario inicial: borrador, aprobación del Gerente y arranque
(RF-62, RN-01, RN-02, RN-03, SN-07, SN-08, SN-09)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.inventario.models import Lote, Movimiento
from apps.inventario.servicios import existencia_de, registrar_movimiento
from apps.levantamiento.models import InventarioInicial, InventarioInicialDetalleLote
from apps.levantamiento.servicios import (
    LevantamientoInvalido,
    agregar_lote,
    agregar_producto,
    aprobar_levantamiento,
    crear_levantamiento,
    quitar_linea,
)
from apps.puntoventa.servicios import existencia_pdv

VENCE = date.today() + timedelta(days=90)


@pytest.fixture
def de_bodega(bodega, jefe_bodega):
    return crear_levantamiento(ubicacion=bodega, usuario=jefe_bodega)


@pytest.fixture
def del_punto(punto_venta, admin_pdv):
    return crear_levantamiento(ubicacion=punto_venta, usuario=admin_pdv)


def lote_contado(levantamiento, producto, usuario, cantidad="30", **extra):
    return agregar_lote(
        levantamiento=levantamiento,
        producto=producto,
        estado_producto="CONGELADO",
        fecha_vencimiento=VENCE,
        cantidad=cantidad,
        usuario=usuario,
        **extra,
    )


# --- Abrir el levantamiento --------------------------------------------------


def test_se_abre_en_borrador_y_queda_en_auditoria(de_bodega, jefe_bodega):
    assert de_bodega.estado == "REGISTRADO"
    assert de_bodega.fecha == timezone.localdate()
    registro = Auditoria.objects.get(entidad="inventario_inicial")
    assert (registro.accion, registro.usuario) == (AccionAuditoria.CREAR, jefe_bodega)


def test_un_solo_levantamiento_por_ubicacion(de_bodega, bodega, gerente):
    """RN-02: en toda la vida del sistema, impuesto también por la base."""
    with pytest.raises(LevantamientoInvalido, match="solo se hace una vez"):
        crear_levantamiento(ubicacion=bodega, usuario=gerente)
    with pytest.raises(IntegrityError), transaction.atomic():
        InventarioInicial.objects.create(ubicacion=bodega, fecha=VENCE, usuario=gerente)


def test_una_ubicacion_que_ya_opera_no_se_levanta(lote, bodega, gerente):
    """SN-08: si ya tiene movimientos quedó arrancada; se corrige con ajustes."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="10", usuario=gerente, ubicacion_destino=bodega
    )
    with pytest.raises(LevantamientoInvalido, match="ya tiene movimientos"):
        crear_levantamiento(ubicacion=bodega, usuario=gerente)


@pytest.mark.parametrize(
    ("perfil", "donde"),
    [("admin_pdv", "bodega"), ("jefe_bodega", "punto_venta"), ("consulta", "bodega")],
)
def test_cada_quien_levanta_lo_que_opera(request, perfil, donde):
    with pytest.raises(PermissionDenied):
        crear_levantamiento(
            ubicacion=request.getfixturevalue(donde), usuario=request.getfixturevalue(perfil)
        )


# --- Registrar lo contado ----------------------------------------------------


def test_el_borrador_no_crea_existencia(de_bodega, producto, jefe_bodega):
    """RN-01: solo la aprobación genera existencia real."""
    lote_contado(de_bodega, producto, jefe_bodega)
    assert not Lote.objects.filter(origen="INVENTARIO_INICIAL").exists()
    assert not Movimiento.objects.exists()


@pytest.mark.parametrize(
    ("extra", "mensaje"),
    [
        ({"cantidad": "0"}, "mayor que cero"),
        ({"cantidad_bultos": 4}, "solo se indican si ya está embultado"),
        ({"estado_producto": "AHUMADO"}, "fresco o congelado"),
    ],
)
def test_lo_contado_en_bodega_debe_ser_valido(de_bodega, producto, jefe_bodega, extra, mensaje):
    datos = {"cantidad": "30", **extra}
    estado = datos.pop("estado_producto", "CONGELADO")
    with pytest.raises(LevantamientoInvalido, match=mensaje):
        agregar_lote(
            levantamiento=de_bodega,
            producto=producto,
            estado_producto=estado,
            fecha_vencimiento=VENCE,
            usuario=jefe_bodega,
            **datos,
        )


def test_bodega_va_por_lote_y_el_pdv_por_producto(de_bodega, del_punto, producto, gerente):
    """SN-09: en el punto de venta no se distingue lote."""
    with pytest.raises(LevantamientoInvalido, match="por producto"):
        lote_contado(del_punto, producto, gerente)
    with pytest.raises(LevantamientoInvalido, match="por lote"):
        agregar_producto(levantamiento=de_bodega, producto=producto, cantidad="5", usuario=gerente)


def test_un_producto_una_vez_en_el_pdv(del_punto, producto, admin_pdv):
    agregar_producto(levantamiento=del_punto, producto=producto, cantidad="5", usuario=admin_pdv)
    with pytest.raises(LevantamientoInvalido, match="ya está en el levantamiento"):
        agregar_producto(
            levantamiento=del_punto, producto=producto, cantidad="2", usuario=admin_pdv
        )


def test_el_borrador_se_corrige_quitando_la_fila(de_bodega, producto, jefe_bodega):
    detalle = lote_contado(de_bodega, producto, jefe_bodega)
    quitar_linea(detalle=detalle, usuario=jefe_bodega)
    assert not de_bodega.lotes.exists()
    assert Auditoria.objects.filter(
        entidad="inventario_inicial_detalle_lote", accion=AccionAuditoria.ANULAR
    ).exists()


# --- Aprobar -----------------------------------------------------------------


def test_aprobar_crea_los_lotes_y_su_existencia(de_bodega, bodega, producto, jefe_bodega, gerente):
    """RF-62: lo crudo nace DISPONIBLE; lo embultado nace cerrado, sin merma."""
    crudo = lote_contado(de_bodega, producto, jefe_bodega, "30")
    en_bultos = lote_contado(
        de_bodega,
        producto,
        jefe_bodega,
        "20",
        estado_lote_resultante="EMBULTADO",
        cantidad_bultos=4,
    )

    aprobar_levantamiento(levantamiento=de_bodega, usuario=gerente)

    de_bodega.refresh_from_db()
    assert de_bodega.estado == "APROBADO"
    assert de_bodega.usuario_aprueba == gerente
    crudo.refresh_from_db()
    en_bultos.refresh_from_db()
    assert crudo.lote.codigo == f"LI-{crudo.lote.pk:06d}"
    assert crudo.lote.origen == "INVENTARIO_INICIAL"
    assert crudo.lote.estado == "DISPONIBLE"
    assert existencia_de(crudo.lote, bodega) == Decimal("30")
    lote = en_bultos.lote
    assert (lote.estado, lote.total_embultado_kg, lote.merma_vs_origen_kg) == (
        "EMBULTADO",
        Decimal("20"),
        None,
    )
    assert lote.cerrado_por == gerente
    assert existencia_de(lote, bodega) == Decimal("20")
    assert Movimiento.objects.filter(tipo="INVENTARIO_INICIAL").count() == 2
    assert Auditoria.objects.filter(
        entidad="inventario_inicial", accion=AccionAuditoria.MODIFICAR
    ).exists()


def test_aprobar_el_pdv_crea_su_existencia_por_producto(
    del_punto, punto_venta, producto, admin_pdv, gerente
):
    agregar_producto(levantamiento=del_punto, producto=producto, cantidad="12", usuario=admin_pdv)
    aprobar_levantamiento(levantamiento=del_punto, usuario=gerente)
    assert existencia_pdv(producto, punto_venta) == Decimal("12")


def test_solo_el_gerente_aprueba(de_bodega, producto, jefe_bodega):
    """RN-03."""
    lote_contado(de_bodega, producto, jefe_bodega)
    with pytest.raises(PermissionDenied):
        aprobar_levantamiento(levantamiento=de_bodega, usuario=jefe_bodega)


def test_no_se_aprueba_vacio_ni_dos_veces(de_bodega, producto, jefe_bodega, gerente):
    with pytest.raises(LevantamientoInvalido, match="no tiene nada contado"):
        aprobar_levantamiento(levantamiento=de_bodega, usuario=gerente)
    lote_contado(de_bodega, producto, jefe_bodega)
    aprobar_levantamiento(levantamiento=de_bodega, usuario=gerente)
    with pytest.raises(LevantamientoInvalido, match="ya fue aprobado"):
        aprobar_levantamiento(levantamiento=de_bodega, usuario=gerente)
    with pytest.raises(LevantamientoInvalido, match="ya fue aprobado"):
        lote_contado(de_bodega, producto, jefe_bodega)


def test_si_empezo_a_operar_mientras_se_contaba_no_se_aprueba(
    de_bodega, bodega, producto, lote, jefe_bodega, gerente
):
    lote_contado(de_bodega, producto, jefe_bodega)
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="5", usuario=gerente, ubicacion_destino=bodega
    )
    with pytest.raises(LevantamientoInvalido, match="empezó a operar"):
        aprobar_levantamiento(levantamiento=de_bodega, usuario=gerente)


@pytest.mark.parametrize(
    "cambios",
    [{"estado": "APROBADO"}, {"estado": "CERRADO"}],
)
def test_la_base_exige_aprobacion_completa(de_bodega, cambios):
    with pytest.raises(IntegrityError), transaction.atomic():
        InventarioInicial.objects.filter(pk=de_bodega.pk).update(**cambios)


def test_la_base_solo_admite_bultos_de_lo_embultado(de_bodega, producto, jefe_bodega):
    detalle = lote_contado(de_bodega, producto, jefe_bodega)
    with pytest.raises(IntegrityError), transaction.atomic():
        InventarioInicialDetalleLote.objects.filter(pk=detalle.pk).update(cantidad_bultos=3)


# --- Pantallas ---------------------------------------------------------------


def test_cada_quien_ve_lo_que_puede_arrancar(
    client, jefe_bodega, admin_pdv, consulta, bodega, punto_venta
):
    lista = reverse("levantamiento:levantamiento_lista")
    client.force_login(jefe_bodega)
    assert client.get(lista).context["por_arrancar"] == [bodega]
    client.force_login(admin_pdv)
    assert client.get(lista).context["por_arrancar"] == [punto_venta]
    client.force_login(consulta)
    assert client.get(lista).context["por_arrancar"] == []


def test_registrar_y_aprobar_desde_la_pantalla(client, jefe_bodega, gerente, bodega, producto):
    client.force_login(jefe_bodega)
    respuesta = client.post(
        reverse("levantamiento:levantamiento_crear", args=[bodega.pk]), follow=True
    )
    levantamiento = InventarioInicial.objects.get()
    assert "registre lo contado" in respuesta.content.decode()

    datos = {
        "producto": producto.pk,
        "estado_producto": "FRESCO",
        "fecha_vencimiento": VENCE.isoformat(),
        "cantidad": "15",
        "estado_lote_resultante": "DISPONIBLE",
        "cantidad_bultos": "",
    }
    client.post(reverse("levantamiento:linea_agregar", args=[levantamiento.pk]), datos)
    assert levantamiento.lotes.count() == 1
    aprobar = reverse("levantamiento:levantamiento_aprobar", args=[levantamiento.pk])
    assert client.post(aprobar).status_code == 403

    client.force_login(gerente)
    respuesta = client.post(aprobar, follow=True)
    assert "ya es existencia real" in respuesta.content.decode()
    levantamiento.refresh_from_db()
    assert levantamiento.estado == "APROBADO"


def test_un_dato_invalido_se_muestra_en_el_formulario(client, jefe_bodega, de_bodega, producto):
    client.force_login(jefe_bodega)
    datos = {
        "producto": producto.pk,
        "estado_producto": "FRESCO",
        "fecha_vencimiento": VENCE.isoformat(),
        "cantidad": "0",
        "estado_lote_resultante": "DISPONIBLE",
    }
    respuesta = client.post(reverse("levantamiento:linea_agregar", args=[de_bodega.pk]), datos)
    assert respuesta.status_code == 200
    assert "cantidad" in respuesta.context["form"].errors
    assert not de_bodega.lotes.exists()


def test_el_pdv_no_ve_el_levantamiento_de_bodega(client, admin_pdv, de_bodega):
    client.force_login(admin_pdv)
    url = reverse("levantamiento:levantamiento_detalle", args=[de_bodega.pk])
    assert client.get(url).status_code == 403


def test_el_menu_ofrece_el_inventario_inicial(client, jefe_bodega):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("inicio")).content.decode()
    assert reverse("levantamiento:levantamiento_lista") in contenido
