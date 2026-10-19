from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.inventario.models import Existencia, Lote, Movimiento
from apps.maestros.models import TipoEmbalaje, Ubicacion
from apps.recepcion.models import DocumentoProveedorLinea, Recepcion
from apps.recepcion.servicios import (
    RecepcionInvalida,
    crear_lote_recepcion,
    diferencia_de_linea,
    peso_recibido,
    registrar_pesada,
)


@pytest.fixture
def pesada(lote, canastilla, jefe_bodega, tunel):
    """Argumentos de una pesada válida: 5 canastillas, 50 kg brutos, a 3 °C (37.50 netos)."""
    return {
        "lote": lote,
        "tipo_embalaje": canastilla,
        "cantidad_embalajes": 5,
        "peso_bruto": Decimal("50.00"),
        "temperatura": Decimal("3.00"),
        "ubicacion_destino": tunel,
        "usuario": jefe_bodega,
    }


def cerrar(linea):
    documento = linea.documento_proveedor
    documento.estado = "CERRADO"
    documento.save()


# --- crear_lote_recepcion ------------------------------------------------------


def test_crear_lote_de_recepcion(linea):
    lote = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    assert lote.origen == "RECEPCION"
    assert lote.documento_proveedor_linea == linea
    assert lote.producto == linea.producto
    assert lote.estado == "DISPONIBLE"
    assert lote.estado_producto == "FRESCO"


def test_el_codigo_del_lote_sale_de_su_id(linea):
    lote = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    assert lote.codigo == f"L-{lote.pk:06d}"
    lote.refresh_from_db()
    assert lote.codigo == f"L-{lote.pk:06d}"


def test_dos_lotes_de_la_misma_linea_tienen_codigos_distintos(linea):
    a = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    b = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 15)
    )
    assert a.codigo != b.codigo
    assert Lote.objects.filter(documento_proveedor_linea=linea).count() == 2


def test_crear_el_lote_no_mueve_inventario(linea):
    crear_lote_recepcion(
        linea=linea, estado_producto="CONGELADO", fecha_vencimiento=date(2026, 12, 1)
    )
    assert Movimiento.objects.count() == 0
    assert Existencia.objects.count() == 0


@pytest.mark.parametrize(
    "estado, vence",
    [
        ("TIBIO", date(2026, 12, 1)),
        ("FRESCO", "2026-12-01"),
        ("FRESCO", None),
        ("FRESCO", date(2026, 9, 30)),  # antes de la fecha del documento (2026-10-01)
    ],
)
def test_lote_con_datos_invalidos_se_rechaza(linea, estado, vence):
    with pytest.raises(RecepcionInvalida):
        crear_lote_recepcion(linea=linea, estado_producto=estado, fecha_vencimiento=vence)
    assert Lote.objects.count() == 0


def test_no_se_crean_lotes_en_un_documento_cerrado(linea):
    cerrar(linea)
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        crear_lote_recepcion(
            linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
        )


# --- registrar_pesada ----------------------------------------------------------


def test_registrar_pesada_crea_la_tanda_con_su_peso_neto(pesada, jefe_bodega, tunel):
    tanda = registrar_pesada(**pesada)
    assert tanda.peso_neto == Decimal("37.50")
    assert tanda.responsable == jefe_bodega
    assert tanda.ubicacion_destino == tunel
    assert Recepcion.objects.count() == 1


def test_registrar_pesada_no_mueve_inventario(pesada):
    registrar_pesada(**pesada)
    assert Movimiento.objects.count() == 0
    assert Existencia.objects.count() == 0


def test_la_pesada_acepta_cantidades_como_texto(pesada):
    pesada.update(peso_bruto="50.00", temperatura="-18.50")
    tanda = registrar_pesada(**pesada)
    assert tanda.peso_neto == Decimal("37.50")
    assert tanda.temperatura == Decimal("-18.50")


def test_pesada_sin_embalaje(pesada, sin_embalaje):
    pesada.update(tipo_embalaje=sin_embalaje, cantidad_embalajes=0)
    assert registrar_pesada(**pesada).peso_neto == Decimal("50.00")


def test_la_pesada_puede_ir_al_cuarto_de_sostenimiento(pesada, bodega):
    pesada["ubicacion_destino"] = bodega
    assert registrar_pesada(**pesada).ubicacion_destino == bodega


def test_la_pesada_puede_ir_a_zona_de_transformacion(pesada, db):
    zona = Ubicacion.objects.create(
        codigo="TRF-01", nombre="Zona de transformación", tipo="ZONA_TRANSFORMACION"
    )
    pesada["ubicacion_destino"] = zona
    assert registrar_pesada(**pesada).ubicacion_destino == zona


@pytest.mark.parametrize("tipo", ["PUNTO_VENTA", "ZONA_BULTOS"])
def test_la_pesada_no_puede_ir_a_punto_de_venta_ni_zona_de_bultos(pesada, tipo):
    pesada["ubicacion_destino"] = Ubicacion.objects.create(
        codigo="X-01", nombre="Otra ubicación", tipo=tipo
    )
    with pytest.raises(RecepcionInvalida, match="no recibe producto"):
        registrar_pesada(**pesada)


def test_la_pesada_no_puede_ir_a_una_ubicacion_inactiva(pesada, tunel):
    tunel.activo = False
    tunel.save()
    with pytest.raises(RecepcionInvalida, match="inactiva"):
        registrar_pesada(**pesada)


def test_la_pesada_no_admite_un_embalaje_inactivo(pesada, canastilla):
    canastilla.activo = False
    canastilla.save()
    with pytest.raises(RecepcionInvalida, match="inactivo"):
        registrar_pesada(**pesada)


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("peso_bruto", Decimal("0")),
        ("peso_bruto", Decimal("-1")),
        ("peso_bruto", "abc"),
        ("peso_bruto", Decimal("10.123")),
        ("peso_bruto", Decimal("NaN")),
        ("peso_bruto", Decimal("100000000")),
        ("temperatura", "abc"),
        ("temperatura", Decimal("3.123")),
        ("temperatura", Decimal("1000")),
        ("temperatura", Decimal("-1000")),
        ("cantidad_embalajes", -1),
        ("cantidad_embalajes", 2.5),
        ("cantidad_embalajes", True),
        ("cantidad_embalajes", "5"),
    ],
)
def test_pesada_con_datos_invalidos_se_rechaza(pesada, campo, valor):
    pesada[campo] = valor
    with pytest.raises(RecepcionInvalida):
        registrar_pesada(**pesada)
    assert Recepcion.objects.count() == 0


def test_la_tara_no_puede_superar_el_peso_bruto(pesada):
    pesada["peso_bruto"] = Decimal("12.50")  # 5 × 2.50 = 12.50 de tara: neto cero
    with pytest.raises(RecepcionInvalida, match="tara"):
        registrar_pesada(**pesada)


def test_no_se_pesa_un_lote_que_no_viene_de_recepcion(pesada, datos_lote):
    otro = Lote.objects.create(codigo="LI-1", origen="INVENTARIO_INICIAL", **datos_lote)
    pesada["lote"] = otro
    with pytest.raises(RecepcionInvalida, match="recepción"):
        registrar_pesada(**pesada)


def test_no_se_pesa_en_un_documento_cerrado(pesada, linea):
    cerrar(linea)
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        registrar_pesada(**pesada)
    assert Recepcion.objects.count() == 0


# --- Peso recibido y diferencia en vivo ----------------------------------------


def test_sin_pesadas_no_hay_peso_recibido(linea):
    assert peso_recibido(linea) == Decimal("0")
    assert diferencia_de_linea(linea) == Decimal("100")


def test_peso_recibido_suma_todas_las_tandas_de_todos_los_lotes(pesada, linea):
    registrar_pesada(**pesada)  # 37.50
    registrar_pesada(**pesada)  # 37.50
    segundo = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 15)
    )
    registrar_pesada(**{**pesada, "lote": segundo})  # 37.50
    assert peso_recibido(linea) == Decimal("112.50")
    assert diferencia_de_linea(linea) == Decimal("-12.50")


def test_peso_recibido_ignora_las_tandas_de_otras_lineas(pesada, linea, producto):
    otra = DocumentoProveedorLinea.objects.create(
        documento_proveedor=linea.documento_proveedor, producto=producto, cantidad=Decimal("40")
    )
    lote_otra = crear_lote_recepcion(
        linea=otra, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    registrar_pesada(**pesada)
    registrar_pesada(**{**pesada, "lote": lote_otra})
    assert peso_recibido(linea) == Decimal("37.50")
    assert peso_recibido(otra) == Decimal("37.50")


def test_peso_recibido_es_una_sola_consulta(pesada, linea):
    registrar_pesada(**pesada)
    registrar_pesada(**pesada)
    with CaptureQueriesContext(connection) as consultas:
        peso_recibido(linea)
    assert len(consultas) == 1


def test_un_lote_puede_pesarse_con_embalajes_distintos(pesada, lote):
    caja = TipoEmbalaje.objects.create(nombre="Caja", peso_tara=Decimal("1.20"))
    registrar_pesada(**pesada)
    registrar_pesada(**{**pesada, "tipo_embalaje": caja, "cantidad_embalajes": 10})
    assert [t.peso_neto for t in lote.tandas.all()] == [Decimal("37.50"), Decimal("38.00")]
