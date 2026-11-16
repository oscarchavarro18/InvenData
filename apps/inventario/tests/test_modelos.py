from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.inventario.models import Existencia, Lote, Movimiento


@pytest.fixture
def datos_movimiento(lote, gerente):
    """Campos mínimos de un movimiento válido; cada prueba agrega o cambia lo que necesite."""
    return {"lote": lote, "usuario": gerente, "cantidad": Decimal("5.00")}


# --- Lote --------------------------------------------------------------------


def test_lote_nace_disponible(lote):
    assert lote.estado == "DISPONIBLE"
    assert lote.cerrado_en is None
    assert lote.total_embultado_kg is None


def test_lote_se_muestra_con_su_codigo(lote):
    assert str(lote) == "L-000001"


def test_lote_derivado_apunta_a_su_lote_de_origen(lote, datos_lote):
    derivado = Lote.objects.create(
        codigo="L-000002", origen="TRANSFORMACION", lote_origen=lote, **datos_lote
    )
    assert list(lote.derivados.all()) == [derivado]


def test_lote_de_inventario_inicial_puede_nacer_embultado(datos_lote):
    lote = Lote.objects.create(
        codigo="L-INI-1", origen="INVENTARIO_INICIAL", estado="EMBULTADO", **datos_lote
    )
    assert lote.estado == "EMBULTADO"


def test_codigo_de_lote_repetido_se_rechaza(lote, datos_lote):
    with pytest.raises(IntegrityError), transaction.atomic():
        Lote.objects.create(codigo="L-000001", origen="INVENTARIO_INICIAL", **datos_lote)


@pytest.mark.parametrize(
    ("origen", "con_linea", "con_lote_origen"),
    [
        ("RECEPCION", False, False),
        ("RECEPCION", True, True),
        ("TRANSFORMACION", False, False),
        ("TRANSFORMACION", True, True),
        ("INVENTARIO_INICIAL", True, False),
        ("INVENTARIO_INICIAL", False, True),
    ],
)
def test_origen_incoherente_con_sus_referencias_se_rechaza(
    origen, con_linea, con_lote_origen, lote, linea, datos_lote
):
    extra = {}
    if con_linea:
        extra["documento_proveedor_linea"] = linea
    if con_lote_origen:
        extra["lote_origen"] = lote
    with pytest.raises(IntegrityError), transaction.atomic():
        Lote.objects.create(codigo="L-X", origen=origen, **extra, **datos_lote)


def test_lote_de_transformacion_no_puede_estar_embultado(lote, datos_lote):
    with pytest.raises(IntegrityError), transaction.atomic():
        Lote.objects.create(
            codigo="L-X",
            origen="TRANSFORMACION",
            lote_origen=lote,
            estado="EMBULTADO",
            **datos_lote,
        )


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("origen", "OTRO"), ("estado_producto", "TIBIO"), ("estado", "PERDIDO")],
)
def test_valores_fuera_de_la_lista_se_rechazan(campo, valor, datos_lote):
    datos = {"codigo": "L-X", "origen": "INVENTARIO_INICIAL", **datos_lote, campo: valor}
    with pytest.raises(IntegrityError), transaction.atomic():
        Lote.objects.create(**datos)


def test_no_se_borra_un_lote_con_derivados(lote, datos_lote):
    Lote.objects.create(codigo="L-000002", origen="TRANSFORMACION", lote_origen=lote, **datos_lote)
    with pytest.raises(ProtectedError):
        lote.delete()


def test_no_se_borra_un_lote_con_movimientos(datos_movimiento, bodega):
    Movimiento.objects.create(tipo="RECEPCION", ubicacion_destino=bodega, **datos_movimiento)
    with pytest.raises(ProtectedError):
        datos_movimiento["lote"].delete()


# --- Movimiento --------------------------------------------------------------


def test_movimiento_registra_la_fecha_y_hora_al_crearse(datos_movimiento, bodega):
    antes = timezone.now()
    movimiento = Movimiento.objects.create(
        tipo="RECEPCION", ubicacion_destino=bodega, **datos_movimiento
    )
    assert antes <= movimiento.fecha_hora <= timezone.now()


def test_movimiento_se_muestra_con_tipo_cantidad_y_lote(datos_movimiento, bodega):
    movimiento = Movimiento.objects.create(
        tipo="RECEPCION", ubicacion_destino=bodega, **datos_movimiento
    )
    assert str(movimiento) == f"RECEPCION 5.00 (lote {datos_movimiento['lote'].pk})"


@pytest.mark.parametrize("cantidad", [Decimal("0"), Decimal("-1.50")])
def test_movimiento_rechaza_cantidad_que_no_es_positiva(cantidad, datos_movimiento, bodega):
    datos_movimiento["cantidad"] = cantidad
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(tipo="RECEPCION", ubicacion_destino=bodega, **datos_movimiento)


def test_movimiento_rechaza_un_tipo_que_no_existe(datos_movimiento):
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(tipo="REGALO", **datos_movimiento)


def test_ajuste_de_conteo_exige_motivo(datos_movimiento, bodega):
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(tipo="AJUSTE_CONTEO", ubicacion_origen=bodega, **datos_movimiento)


def test_ajuste_de_conteo_con_motivo_es_valido(datos_movimiento, bodega):
    movimiento = Movimiento.objects.create(
        tipo="AJUSTE_CONTEO",
        motivo_ajuste="PERDIDA",
        ubicacion_origen=bodega,
        observacion="Conteo físico del día",
        **datos_movimiento,
    )
    assert movimiento.pk is not None


def test_motivo_de_ajuste_solo_aplica_a_ajustes_de_conteo(datos_movimiento, bodega):
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(
            tipo="RECEPCION",
            motivo_ajuste="PERDIDA",
            ubicacion_destino=bodega,
            **datos_movimiento,
        )


def test_motivo_de_ajuste_fuera_de_la_lista_se_rechaza(datos_movimiento, bodega):
    with pytest.raises(IntegrityError), transaction.atomic():
        Movimiento.objects.create(
            tipo="AJUSTE_CONTEO",
            motivo_ajuste="ANTOJO",
            ubicacion_origen=bodega,
            **datos_movimiento,
        )


def test_un_reverso_apunta_al_movimiento_que_corrige(datos_movimiento, bodega):
    original = Movimiento.objects.create(
        tipo="RECEPCION", ubicacion_destino=bodega, **datos_movimiento
    )
    reverso = Movimiento.objects.create(
        tipo="AJUSTE_CONTEO",
        motivo_ajuste="ERROR_CONTEO",
        ubicacion_origen=bodega,
        movimiento_reversado=original,
        observacion="Se digitó mal la cantidad",
        **datos_movimiento,
    )
    assert list(original.reversos.all()) == [reverso]


def test_los_movimientos_se_listan_del_mas_reciente_al_mas_antiguo(datos_movimiento, bodega):
    ahora = timezone.now()
    viejo = Movimiento.objects.create(
        tipo="RECEPCION",
        ubicacion_destino=bodega,
        fecha_hora=ahora - timedelta(hours=2),
        **datos_movimiento,
    )
    nuevo = Movimiento.objects.create(
        tipo="RECEPCION", ubicacion_destino=bodega, fecha_hora=ahora, **datos_movimiento
    )
    assert list(Movimiento.objects.all()) == [nuevo, viejo]


# --- Existencia --------------------------------------------------------------


def test_existencia_se_identifica_por_lote_y_ubicacion(lote, bodega):
    existencia = Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("40"))
    assert existencia.pk == (lote.pk, bodega.pk)
    assert Existencia.objects.get(pk=(lote.pk, bodega.pk)).cantidad == Decimal("40.00")


def test_no_hay_dos_existencias_para_el_mismo_lote_y_ubicacion(lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("40"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("10"))


def test_un_lote_puede_tener_existencia_en_varias_ubicaciones(lote, bodega, punto_venta):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("40"))
    Existencia.objects.create(lote=lote, ubicacion=punto_venta, cantidad=Decimal("10"))
    assert lote.existencias.count() == 2


def test_existencia_rechaza_cantidad_negativa(lote, bodega):
    with pytest.raises(IntegrityError), transaction.atomic():
        Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("-0.01"))


def test_existencia_en_cero_es_valida(lote, bodega):
    existencia = Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("0"))
    assert existencia.cantidad == Decimal("0")


def test_no_se_borra_un_lote_con_existencias(lote, bodega):
    Existencia.objects.create(lote=lote, ubicacion=bodega, cantidad=Decimal("40"))
    with pytest.raises(ProtectedError):
        lote.delete()
