"""Despacho mayorista y constancia de entrega (RF-35, RF-36, RF-37, RN-27, RD-04)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.auditoria.models import AccionAuditoria, Auditoria, Evidencia
from apps.despacho.models import DespachoDetalle, DespachoMayorista
from apps.despacho.servicios import DespachoInvalido, registrar_entrega
from apps.despacho.tests.conftest import lineas_de
from apps.inventario.models import Movimiento
from apps.inventario.servicios import ExistenciaInsuficiente, existencia_de

FIRMA = [[[100, 500], [200, 400], [300, 600]], [[400, 500], [500, 500]]]


@pytest.fixture
def media(settings, tmp_path):
    """Las fotos de prueba van a una carpeta temporal, no a la de la aplicación."""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def _foto(nombre="firmado.png", tipo="image/png", tamano=100):
    return SimpleUploadedFile(nombre, b"x" * tamano, content_type=tipo)


# --- Despachar ---------------------------------------------------------------


def test_despachar_descuenta_la_existencia_de_una_vez(despachar, alistado, en_bultos, zona_bultos):
    """RF-36, RN-27, RD-04: sin confirmación posterior de nadie."""
    despacho = despachar(alistado)

    assert existencia_de(en_bultos, zona_bultos) == Decimal("40")
    movimiento = Movimiento.objects.get(tipo="DESPACHO_MAYORISTA")
    assert movimiento.ubicacion_origen == zona_bultos
    assert movimiento.ubicacion_destino is None
    assert movimiento.cantidad == Decimal("60")
    alistado.refresh_from_db()
    assert alistado.estado == "DESPACHADO"
    assert despacho.placa_vehiculo == "ABC123"
    (detalle,) = despacho.detalles.all()
    assert (detalle.cantidad, detalle.cantidad_bultos_cajas) == (Decimal("60"), 3)


def test_se_descuenta_lo_realmente_cargado(despachar, alistado, en_bultos, zona_bultos):
    despachar(alistado, lineas=lineas_de(alistado, cantidad=Decimal("58.50")))
    assert existencia_de(en_bultos, zona_bultos) == Decimal("41.50")


def test_el_despacho_queda_en_auditoria(despachar, alistado):
    despacho = despachar(alistado)
    assert Auditoria.objects.get(entidad="despacho_mayorista").registro_id == despacho.pk
    cambio = Auditoria.objects.get(entidad="pedido", valor_nuevo__estado="DESPACHADO")
    assert cambio.valor_anterior["estado"] == "ALISTADO"


def test_solo_se_despacha_un_pedido_alistado_y_una_vez(despachar, alistado):
    despachar(alistado)
    with pytest.raises(DespachoInvalido, match="solo se despacha un pedido alistado"):
        despachar(alistado, numero_documento="R-0002")
    assert DespachoMayorista.objects.count() == 1


def test_el_documento_no_se_repite(despachar, alistado, alistar):
    despachar(alistado)
    otro = alistar("10")
    with pytest.raises(DespachoInvalido, match="Ya existe un despacho con remisión R-0001"):
        despachar(otro)


@pytest.mark.parametrize("caso", ["sin_lineas", "repetida"])
def test_deben_venir_todas_las_lineas_una_vez(despachar, alistado, caso):
    lineas = lineas_de(alistado)
    lineas = [] if caso == "sin_lineas" else lineas * 2
    with pytest.raises(DespachoInvalido, match="una sola vez"):
        despachar(alistado, lineas=lineas)


def test_sin_existencia_suficiente_no_queda_nada(despachar, alistado, en_bultos, zona_bultos):
    with pytest.raises(ExistenciaInsuficiente):
        despachar(alistado, lineas=lineas_de(alistado, cantidad=Decimal("150")))
    assert existencia_de(en_bultos, zona_bultos) == Decimal("100")
    assert not DespachoMayorista.objects.exists()
    alistado.refresh_from_db()
    assert alistado.estado == "ALISTADO"


@pytest.mark.parametrize(
    "cambios",
    [
        {"placa_vehiculo": "  "},
        {"nombre_conductor": ""},
        {"numero_documento": ""},
        {"tipo_documento": "PAGARE"},
        {"valor_total": "-1"},
    ],
)
def test_los_datos_del_documento_son_obligatorios(despachar, alistado, cambios):
    """RF-35: placa, conductor y número de documento."""
    with pytest.raises(DespachoInvalido):
        despachar(alistado, **cambios)


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_bodega_despacha(request, despachar, alistado, perfil):
    with pytest.raises(PermissionDenied):
        despachar(alistado, usuario=request.getfixturevalue(perfil))


def test_un_lote_alistado_sale_una_sola_vez(despachar, alistado):
    despacho = despachar(alistado)
    detalle = despacho.detalles.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        DespachoDetalle.objects.create(
            despacho_mayorista=despacho,
            alistamiento_detalle=detalle.alistamiento_detalle,
            cantidad=Decimal("1"),
        )


# --- Constancia de entrega ---------------------------------------------------


def test_la_firma_digital_queda_como_constancia(despachar, alistado, jefe_bodega):
    """RF-37: firma capturada en pantalla al momento de la entrega."""
    despacho = despachar(alistado)
    registrar_entrega(
        despacho=despacho, usuario=jefe_bodega, nombre_recibe=" Ana Ruiz ", firma=FIRMA
    )
    despacho.refresh_from_db()
    assert despacho.nombre_recibe == "Ana Ruiz"
    assert despacho.firma_recibe_digital == FIRMA
    assert despacho.fecha_hora_recepcion is not None
    assert Auditoria.objects.filter(
        entidad="despacho_mayorista", accion=AccionAuditoria.MODIFICAR
    ).exists()


def test_la_foto_del_papel_firmado_queda_como_evidencia(despachar, alistado, jefe_bodega, media):
    """RF-37: documento firmado en papel y fotografiado."""
    despacho = despachar(alistado)
    registrar_entrega(
        despacho=despacho, usuario=jefe_bodega, nombre_recibe="Ana Ruiz", archivo=_foto()
    )
    evidencia = Evidencia.objects.get()
    assert (evidencia.entidad, evidencia.registro_id) == ("despacho_mayorista", despacho.pk)
    assert evidencia.tipo_mime == "image/png"
    assert Auditoria.objects.filter(entidad="evidencia").exists()


def test_la_entrega_exige_firma_o_foto(despachar, alistado, jefe_bodega):
    despacho = despachar(alistado)
    with pytest.raises(DespachoInvalido, match="Adjunte la foto"):
        registrar_entrega(despacho=despacho, usuario=jefe_bodega, nombre_recibe="Ana")


@pytest.mark.parametrize(
    ("archivo", "mensaje"),
    [
        (_foto("notas.txt", "text/plain"), "foto"),
        (_foto(tamano=5 * 1024 * 1024 + 1), "5 MB"),
    ],
)
def test_la_evidencia_debe_ser_una_foto_o_pdf_liviano(
    despachar, alistado, jefe_bodega, media, archivo, mensaje
):
    despacho = despachar(alistado)
    with pytest.raises(DespachoInvalido, match=mensaje):
        registrar_entrega(
            despacho=despacho, usuario=jefe_bodega, nombre_recibe="Ana", archivo=archivo
        )
    assert not Evidencia.objects.exists()


@pytest.mark.parametrize(
    "firma", [[], [[]], [[[1]]], [[[2000, 1]]], "trazo", [[[True, 1]]], [[[1, "a"]]]]
)
def test_una_firma_mal_formada_se_rechaza(despachar, alistado, jefe_bodega, firma):
    despacho = despachar(alistado)
    with pytest.raises(DespachoInvalido, match="firma digital"):
        registrar_entrega(despacho=despacho, usuario=jefe_bodega, nombre_recibe="Ana", firma=firma)


def test_la_entrega_se_registra_una_sola_vez(despachar, alistado, jefe_bodega):
    despacho = despachar(alistado)
    registrar_entrega(despacho=despacho, usuario=jefe_bodega, nombre_recibe="Ana", firma=FIRMA)
    with pytest.raises(DespachoInvalido, match="ya tiene su constancia"):
        registrar_entrega(despacho=despacho, usuario=jefe_bodega, nombre_recibe="Otra", firma=FIRMA)


def test_la_base_exige_la_entrega_completa(despachar, alistado):
    despacho = despachar(alistado)
    with pytest.raises(IntegrityError), transaction.atomic():
        DespachoMayorista.objects.filter(pk=despacho.pk).update(nombre_recibe="Ana")


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_bodega_registra_la_entrega(request, despachar, alistado, perfil):
    despacho = despachar(alistado)
    with pytest.raises(PermissionDenied):
        registrar_entrega(
            despacho=despacho,
            usuario=request.getfixturevalue(perfil),
            nombre_recibe="Ana",
            firma=FIRMA,
        )
