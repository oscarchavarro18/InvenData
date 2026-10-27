"""Ventas a consumidor final y a restaurante, y consultas del PDV (RF-46, RF-47, RF-49,
RN-31, RN-33, RD-01, RNF-01)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Perfil, Usuario
from apps.auditoria.models import AccionAuditoria, Auditoria, Evidencia
from apps.maestros.models import Ubicacion
from apps.puntoventa.consultas import historial_pdv, totales_del_rango, ventas_del_dia
from apps.puntoventa.models import (
    MovimientoPuntoVenta,
    VentaConsumidorFinal,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemision,
)
from apps.puntoventa.servicios import (
    ErrorPuntoVenta,
    ExistenciaPdvInsuficiente,
    VentaInvalida,
    existencia_pdv,
    registrar_venta_consumidor,
    registrar_venta_restaurante,
)
from apps.puntoventa.tests.conftest import linea


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def vender(punto_venta, usuario, lineas, factura="FE-1001"):
    return registrar_venta_consumidor(
        ubicacion=punto_venta, numero_factura_siigo=factura, lineas=lineas, usuario=usuario
    )


def remitir(punto_venta, usuario, cliente, lineas, **extra):
    return registrar_venta_restaurante(
        ubicacion=punto_venta, cliente=cliente, lineas=lineas, usuario=usuario, **extra
    )


# --- Consumidor final --------------------------------------------------------


def test_la_venta_descuenta_cada_producto_de_inmediato(punto_venta, admin_pdv, con_stock, tilapia):
    """RF-46 y RN-31: varios productos en una venta, cada uno con su salida."""
    lineas = [linea(con_stock, "12.5"), linea(tilapia, "4")]
    venta = vender(punto_venta, admin_pdv, lineas, "fe-1001")

    assert venta.numero_factura_siigo == "FE-1001"
    assert venta.fecha == timezone.localdate()
    assert existencia_pdv(con_stock, punto_venta) == Decimal("17.50")
    assert existencia_pdv(tilapia, punto_venta) == Decimal("6")
    assert venta.lineas.count() == 2
    assert MovimientoPuntoVenta.objects.filter(tipo="VENTA").count() == 2
    registro = Auditoria.objects.get(entidad="venta_consumidor_final")
    assert registro.accion == AccionAuditoria.CREAR


def test_la_factura_de_siigo_es_obligatoria_y_unica(punto_venta, admin_pdv, con_stock):
    """RD-01 y RN-33: el sistema solo referencia la factura que generó Siigo."""
    with pytest.raises(VentaInvalida, match="número de la factura"):
        vender(punto_venta, admin_pdv, [linea(con_stock, "1")], "  ")
    vender(punto_venta, admin_pdv, [linea(con_stock, "1")])
    with pytest.raises(VentaInvalida, match="ya está registrada"):
        vender(punto_venta, admin_pdv, [linea(con_stock, "1")], "fe-1001")


def test_sin_existencia_no_queda_nada_a_medias(punto_venta, admin_pdv, con_stock, tilapia):
    with pytest.raises(ExistenciaPdvInsuficiente):
        vender(punto_venta, admin_pdv, [linea(con_stock, "5"), linea(tilapia, "10.01")])
    assert existencia_pdv(con_stock, punto_venta) == Decimal("30")
    assert not VentaConsumidorFinal.objects.exists()
    assert not MovimientoPuntoVenta.objects.filter(tipo="VENTA").exists()


@pytest.mark.parametrize(
    ("lineas", "mensaje"),
    [
        ([], "al menos un producto"),
        ("repetida", "una sola vez"),
        ("cero", "mayor que cero"),
    ],
)
def test_las_lineas_deben_ser_validas(punto_venta, admin_pdv, con_stock, lineas, mensaje):
    if lineas == "repetida":
        lineas = [linea(con_stock, "1"), linea(con_stock, "2")]
    elif lineas == "cero":
        lineas = [linea(con_stock, "0")]
    with pytest.raises(VentaInvalida, match=mensaje):
        vender(punto_venta, admin_pdv, lineas)


def test_el_gerente_vende_en_cualquier_punto(punto_venta, gerente, con_stock):
    vender(punto_venta, gerente, [linea(con_stock, "1")])
    assert existencia_pdv(con_stock, punto_venta) == Decimal("29")


def test_solo_vende_quien_opera_ese_punto(punto_venta, con_stock, jefe_bodega, consulta, db):
    """RN-06: el administrador de otro punto, bodega y consulta no venden aquí."""
    otro = Usuario.objects.create_user(
        "otro_pdv",
        "ClaveSegura123",
        nombre_completo="Otro administrador",
        perfil=Perfil.objects.get(codigo="ADMIN_PDV"),
        ubicacion=Ubicacion.objects.create(
            codigo="PDV-02", nombre="Punto de venta 2", tipo="PUNTO_VENTA"
        ),
    )
    for usuario in (otro, jefe_bodega, consulta):
        with pytest.raises(PermissionDenied):
            vender(punto_venta, usuario, [linea(con_stock, "1")])


def test_no_se_vende_desde_bodega(bodega, gerente, producto):
    with pytest.raises(VentaInvalida, match="no es un punto de venta"):
        vender(bodega, gerente, [linea(producto, "1")])


def test_la_base_no_repite_un_producto_en_la_venta(punto_venta, admin_pdv, con_stock):
    venta = vender(punto_venta, admin_pdv, [linea(con_stock, "1")])
    with pytest.raises(IntegrityError), transaction.atomic():
        VentaConsumidorFinalLinea.objects.create(
            venta_consumidor_final=venta, producto=con_stock, cantidad=Decimal("1")
        )


# --- Restaurante y autorización de datos -------------------------------------


def test_la_remision_se_numera_sola_y_descuenta(punto_venta, admin_pdv, con_stock, restaurante):
    """RF-47 y RN-33: remisión propia, sin factura de Siigo, con el cliente identificado."""
    venta = remitir(punto_venta, admin_pdv, restaurante, [linea(con_stock, "8")])
    assert venta.numero_documento == f"RM-{venta.pk:06d}"
    assert venta.cliente == restaurante
    assert existencia_pdv(con_stock, punto_venta) == Decimal("22")


def test_sin_autorizacion_de_datos_no_hay_remision(
    punto_venta, admin_pdv, con_stock, restaurante_sin_autorizar
):
    """RNF-01: sin autorización no se guardan las compras del cliente."""
    with pytest.raises(VentaInvalida, match="no ha autorizado"):
        remitir(punto_venta, admin_pdv, restaurante_sin_autorizar, [linea(con_stock, "8")])
    restaurante_sin_autorizar.refresh_from_db()
    assert restaurante_sin_autorizar.autoriza_tratamiento_datos is False
    assert existencia_pdv(con_stock, punto_venta) == Decimal("30")


def test_la_autorizacion_se_toma_en_el_mostrador_una_vez(
    punto_venta, admin_pdv, con_stock, restaurante_sin_autorizar, media
):
    foto = SimpleUploadedFile("autorizacion.jpg", b"JPG", content_type="image/jpeg")
    remitir(
        punto_venta,
        admin_pdv,
        restaurante_sin_autorizar,
        [linea(con_stock, "8")],
        autoriza_datos=True,
        evidencia=foto,
    )

    cliente = restaurante_sin_autorizar
    cliente.refresh_from_db()
    assert cliente.autoriza_tratamiento_datos is True
    assert cliente.fecha_autorizacion == timezone.localdate()
    cambio = Auditoria.objects.get(entidad="cliente", accion=AccionAuditoria.MODIFICAR)
    assert cambio.usuario == admin_pdv
    assert cambio.valor_anterior["autoriza_tratamiento_datos"] is False
    evidencia = Evidencia.objects.get()
    assert (evidencia.entidad, evidencia.registro_id) == ("cliente", cliente.pk)
    # La segunda vez ya no se pregunta.
    remitir(punto_venta, admin_pdv, cliente, [linea(con_stock, "1")])
    assert VentaRestauranteRemision.objects.count() == 2


def test_una_prueba_que_no_es_foto_ni_pdf_se_rechaza(
    punto_venta, admin_pdv, con_stock, restaurante_sin_autorizar, media
):
    archivo = SimpleUploadedFile("notas.txt", b"x", content_type="text/plain")
    with pytest.raises(VentaInvalida, match="foto"):
        remitir(
            punto_venta,
            admin_pdv,
            restaurante_sin_autorizar,
            [linea(con_stock, "1")],
            autoriza_datos=True,
            evidencia=archivo,
        )
    restaurante_sin_autorizar.refresh_from_db()
    assert restaurante_sin_autorizar.autoriza_tratamiento_datos is False


def test_si_la_venta_falla_la_autorizacion_tampoco_queda(
    punto_venta, admin_pdv, con_stock, restaurante_sin_autorizar
):
    """Todo o nada: la autorización va en la misma transacción que la venta."""
    with pytest.raises(ErrorPuntoVenta):
        remitir(
            punto_venta,
            admin_pdv,
            restaurante_sin_autorizar,
            [linea(con_stock, "31")],
            autoriza_datos=True,
        )
    restaurante_sin_autorizar.refresh_from_db()
    assert restaurante_sin_autorizar.autoriza_tratamiento_datos is False


def test_un_cliente_inactivo_no_compra(punto_venta, admin_pdv, con_stock, restaurante):
    restaurante.activo = False
    restaurante.save()
    with pytest.raises(VentaInvalida, match="inactivo"):
        remitir(punto_venta, admin_pdv, restaurante, [linea(con_stock, "1")])


# --- Consultas ---------------------------------------------------------------


def test_ventas_del_dia_suma_los_dos_canales(punto_venta, admin_pdv, con_stock, restaurante):
    vender(punto_venta, admin_pdv, [linea(con_stock, "2")])
    remitir(punto_venta, admin_pdv, restaurante, [linea(con_stock, "3")])
    assert ventas_del_dia(punto_venta) == {"ventas": 2, "kg": Decimal("5")}


def test_el_historial_muestra_entradas_y_ventas_del_rango(
    punto_venta, admin_pdv, con_stock, producto
):
    """RF-49."""
    vender(punto_venta, admin_pdv, [linea(con_stock, "2")])
    hoy = timezone.localdate()

    movimientos = historial_pdv(punto_venta, hoy, hoy)

    assert [(m.tipo, m.entrada) for m in movimientos] == [
        ("ENTRADA_TRASLADO", True),
        ("VENTA", False),
    ]
    assert totales_del_rango(punto_venta, hoy, hoy) == (Decimal("30"), Decimal("2"))
    ayer = hoy - timedelta(days=1)
    assert historial_pdv(punto_venta, ayer, ayer) == []
