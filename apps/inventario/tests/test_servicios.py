from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.inventario.models import Existencia, Lote, Movimiento
from apps.inventario.servicios import (
    ExistenciaInsuficiente,
    MovimientoInvalido,
    existencia_de,
    registrar_movimiento,
)
from apps.maestros.models import Ubicacion


@pytest.fixture
def tunel(db):
    return Ubicacion.objects.create(
        codigo="TUN-01", nombre="Túnel de congelación 1", tipo="TUNEL_CONGELACION"
    )


def recibir(lote, ubicacion, cantidad, usuario):
    """Deja `cantidad` del lote en la ubicación, como lo haría una recepción."""
    return registrar_movimiento(
        lote=lote,
        tipo="RECEPCION",
        cantidad=cantidad,
        usuario=usuario,
        ubicacion_destino=ubicacion,
    )


# --- Entradas y salidas ------------------------------------------------------


def test_una_recepcion_crea_el_movimiento_y_la_existencia(lote, bodega, gerente):
    movimiento = recibir(lote, bodega, "40.50", gerente)

    assert movimiento.tipo == "RECEPCION"
    assert movimiento.cantidad == Decimal("40.50")
    assert movimiento.ubicacion_origen is None
    assert movimiento.ubicacion_destino == bodega
    assert existencia_de(lote, bodega) == Decimal("40.50")


def test_dos_recepciones_en_la_misma_ubicacion_se_suman(lote, bodega, gerente):
    recibir(lote, bodega, "40", gerente)
    recibir(lote, bodega, "10.25", gerente)

    assert existencia_de(lote, bodega) == Decimal("50.25")
    assert Existencia.objects.filter(lote=lote).count() == 1
    assert Movimiento.objects.filter(lote=lote).count() == 2


@pytest.mark.parametrize("tipo", ["RECEPCION", "INVENTARIO_INICIAL", "PRODUCCION_TRANSFORMACION"])
def test_los_tipos_de_entrada_suman_en_el_destino(tipo, lote, bodega, gerente):
    registrar_movimiento(
        lote=lote, tipo=tipo, cantidad=20, usuario=gerente, ubicacion_destino=bodega
    )
    assert existencia_de(lote, bodega) == Decimal("20")


@pytest.mark.parametrize(
    "tipo", ["CONSUMO_TRANSFORMACION", "DESPACHO_MAYORISTA", "MERMA_EMBULTAJE"]
)
def test_los_tipos_de_salida_restan_en_el_origen(tipo, lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    movimiento = registrar_movimiento(
        lote=lote, tipo=tipo, cantidad=15, usuario=gerente, ubicacion_origen=bodega
    )
    assert existencia_de(lote, bodega) == Decimal("35")
    assert movimiento.ubicacion_destino is None


def test_sacar_todo_deja_la_existencia_en_cero(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    registrar_movimiento(
        lote=lote, tipo="DESPACHO_MAYORISTA", cantidad=50, usuario=gerente, ubicacion_origen=bodega
    )
    assert existencia_de(lote, bodega) == Decimal("0")
    assert Existencia.objects.filter(lote=lote, ubicacion=bodega).exists()


# --- Traslados ---------------------------------------------------------------


@pytest.mark.parametrize("tipo", ["TRASLADO_INTERNO", "EMBULTAJE"])
def test_los_traslados_restan_en_el_origen_y_suman_en_el_destino(
    tipo, lote, bodega, tunel, gerente
):
    recibir(lote, bodega, 50, gerente)
    registrar_movimiento(
        lote=lote,
        tipo=tipo,
        cantidad=30,
        usuario=gerente,
        ubicacion_origen=bodega,
        ubicacion_destino=tunel,
    )
    assert existencia_de(lote, bodega) == Decimal("20")
    assert existencia_de(lote, tunel) == Decimal("30")


def test_el_traslado_a_punto_de_venta_solo_resta_en_bodega(lote, bodega, punto_venta, gerente):
    recibir(lote, bodega, 50, gerente)
    movimiento = registrar_movimiento(
        lote=lote,
        tipo="TRASLADO_PDV",
        cantidad=20,
        usuario=gerente,
        ubicacion_origen=bodega,
        ubicacion_destino=punto_venta,
    )
    assert existencia_de(lote, bodega) == Decimal("30")
    assert not Existencia.objects.filter(ubicacion=punto_venta).exists()
    assert movimiento.ubicacion_destino == punto_venta


def test_el_destino_de_un_traslado_a_punto_de_venta_debe_ser_un_punto_de_venta(
    lote, bodega, tunel, gerente
):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="punto de venta"):
        registrar_movimiento(
            lote=lote,
            tipo="TRASLADO_PDV",
            cantidad=20,
            usuario=gerente,
            ubicacion_origen=bodega,
            ubicacion_destino=tunel,
        )


def test_un_traslado_no_puede_salir_y_llegar_a_la_misma_ubicacion(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="misma ubicación"):
        registrar_movimiento(
            lote=lote,
            tipo="TRASLADO_INTERNO",
            cantidad=10,
            usuario=gerente,
            ubicacion_origen=bodega,
            ubicacion_destino=bodega,
        )


# --- La existencia nunca queda negativa --------------------------------------


def test_no_se_puede_sacar_mas_de_lo_que_hay(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(ExistenciaInsuficiente, match="disponible 50.00, solicitado 50.01"):
        registrar_movimiento(
            lote=lote,
            tipo="DESPACHO_MAYORISTA",
            cantidad="50.01",
            usuario=gerente,
            ubicacion_origen=bodega,
        )
    assert existencia_de(lote, bodega) == Decimal("50")
    assert Movimiento.objects.count() == 1  # solo la recepción


def test_no_se_puede_sacar_de_donde_nunca_hubo_existencia(lote, bodega, gerente):
    with pytest.raises(ExistenciaInsuficiente, match="disponible 0"):
        registrar_movimiento(
            lote=lote,
            tipo="DESPACHO_MAYORISTA",
            cantidad=1,
            usuario=gerente,
            ubicacion_origen=bodega,
        )
    assert not Existencia.objects.exists()


def test_un_traslado_sin_saldo_no_deja_nada_a_medias(lote, bodega, tunel, gerente):
    recibir(lote, bodega, 10, gerente)
    with pytest.raises(ExistenciaInsuficiente):
        registrar_movimiento(
            lote=lote,
            tipo="TRASLADO_INTERNO",
            cantidad=11,
            usuario=gerente,
            ubicacion_origen=bodega,
            ubicacion_destino=tunel,
        )
    assert existencia_de(lote, bodega) == Decimal("10")
    assert existencia_de(lote, tunel) == Decimal("0")
    assert Movimiento.objects.count() == 1


# --- Reglas de forma ---------------------------------------------------------


@pytest.mark.parametrize(
    ("tipo", "con_origen", "con_destino"),
    [
        ("RECEPCION", True, True),
        ("RECEPCION", True, False),
        ("RECEPCION", False, False),
        ("DESPACHO_MAYORISTA", True, True),
        ("DESPACHO_MAYORISTA", False, True),
        ("DESPACHO_MAYORISTA", False, False),
        ("TRASLADO_INTERNO", True, False),
        ("TRASLADO_INTERNO", False, True),
        ("TRASLADO_INTERNO", False, False),
        ("EMBULTAJE", True, False),
    ],
)
def test_cada_tipo_exige_su_combinacion_de_origen_y_destino(
    tipo, con_origen, con_destino, lote, bodega, tunel, gerente
):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="combinación"):
        registrar_movimiento(
            lote=lote,
            tipo=tipo,
            cantidad=5,
            usuario=gerente,
            ubicacion_origen=bodega if con_origen else None,
            ubicacion_destino=tunel if con_destino else None,
        )
    assert existencia_de(lote, bodega) == Decimal("50")


def test_en_un_punto_de_venta_no_se_lleva_existencia_por_lote(lote, punto_venta, gerente):
    with pytest.raises(MovimientoInvalido, match="punto de venta"):
        recibir(lote, punto_venta, 10, gerente)


@pytest.mark.parametrize("cantidad", [0, -1, "-0.01", "1.234", "abc", None, "NaN", "100000000"])
def test_la_cantidad_debe_ser_positiva_con_dos_decimales_y_numerica(
    cantidad, lote, bodega, gerente
):
    with pytest.raises(MovimientoInvalido):
        recibir(lote, bodega, cantidad, gerente)
    assert not Movimiento.objects.exists()


def test_un_tipo_de_movimiento_que_no_existe_se_rechaza(lote, bodega, gerente):
    with pytest.raises(MovimientoInvalido, match="no existe"):
        registrar_movimiento(
            lote=lote, tipo="REGALO", cantidad=1, usuario=gerente, ubicacion_destino=bodega
        )


def test_el_motivo_de_ajuste_solo_aplica_a_ajustes_de_conteo(lote, bodega, gerente):
    with pytest.raises(MovimientoInvalido, match="solo aplica"):
        registrar_movimiento(
            lote=lote,
            tipo="RECEPCION",
            cantidad=1,
            usuario=gerente,
            ubicacion_destino=bodega,
            motivo_ajuste="PERDIDA",
        )


def test_un_lote_embultado_no_admite_nuevos_embultajes(lote, bodega, tunel, gerente):
    recibir(lote, bodega, 50, gerente)
    # Otra sesión lo marca como embultado: el servicio debe ver el estado real, no el viejo.
    Lote.objects.filter(pk=lote.pk).update(estado="EMBULTADO")
    with pytest.raises(MovimientoInvalido, match="ya está embultado"):
        registrar_movimiento(
            lote=lote,
            tipo="EMBULTAJE",
            cantidad=10,
            usuario=gerente,
            ubicacion_origen=bodega,
            ubicacion_destino=tunel,
        )


def test_la_fecha_y_hora_se_respeta_si_se_indica(lote, bodega, gerente):
    ayer = timezone.now() - timedelta(days=1)
    movimiento = registrar_movimiento(
        lote=lote,
        tipo="RECEPCION",
        cantidad=1,
        usuario=gerente,
        ubicacion_destino=bodega,
        fecha_hora=ayer,
    )
    assert movimiento.fecha_hora == ayer


# --- Ajustes de conteo (RF-53) -----------------------------------------------


def test_un_ajuste_por_perdida_resta_y_deja_su_justificacion(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    movimiento = registrar_movimiento(
        lote=lote,
        tipo="AJUSTE_CONTEO",
        cantidad=3,
        usuario=gerente,
        ubicacion_origen=bodega,
        motivo_ajuste="PERDIDA",
        observacion="  Se dañaron 3 kg por corte de energía  ",
    )
    assert existencia_de(lote, bodega) == Decimal("47")
    assert movimiento.motivo_ajuste == "PERDIDA"
    assert movimiento.observacion == "Se dañaron 3 kg por corte de energía"


def test_un_ajuste_por_sobrante_suma(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    registrar_movimiento(
        lote=lote,
        tipo="AJUSTE_CONTEO",
        cantidad=2,
        usuario=gerente,
        ubicacion_destino=bodega,
        motivo_ajuste="SOBRANTE",
        observacion="El conteo físico encontró 2 kg más",
    )
    assert existencia_de(lote, bodega) == Decimal("52")


@pytest.mark.parametrize("motivo", ["ERROR_CONTEO", "OTRO"])
@pytest.mark.parametrize("resta", [True, False])
def test_los_motivos_neutros_pueden_sumar_o_restar(motivo, resta, lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    registrar_movimiento(
        lote=lote,
        tipo="AJUSTE_CONTEO",
        cantidad=5,
        usuario=gerente,
        ubicacion_origen=bodega if resta else None,
        ubicacion_destino=None if resta else bodega,
        motivo_ajuste=motivo,
        observacion="Corrección documentada",
    )
    assert existencia_de(lote, bodega) == Decimal("45" if resta else "55")


def test_solo_el_gerente_registra_ajustes_de_conteo(lote, bodega, gerente, jefe_bodega):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(PermissionDenied):
        registrar_movimiento(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            cantidad=3,
            usuario=jefe_bodega,
            ubicacion_origen=bodega,
            motivo_ajuste="PERDIDA",
            observacion="Intento sin permiso",
        )
    assert existencia_de(lote, bodega) == Decimal("50")


@pytest.mark.parametrize("motivo", [None, "ANTOJO"])
def test_el_ajuste_exige_un_motivo_de_la_lista(motivo, lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="motivo"):
        registrar_movimiento(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            cantidad=3,
            usuario=gerente,
            ubicacion_origen=bodega,
            motivo_ajuste=motivo,
            observacion="Sin motivo válido",
        )


@pytest.mark.parametrize("observacion", [None, "", "   "])
def test_el_ajuste_exige_una_observacion_escrita(observacion, lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="observación"):
        registrar_movimiento(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            cantidad=3,
            usuario=gerente,
            ubicacion_origen=bodega,
            motivo_ajuste="PERDIDA",
            observacion=observacion,
        )


@pytest.mark.parametrize(
    ("motivo", "resta"),
    [("PERDIDA", False), ("VENCIMIENTO", False), ("SOBRANTE", True)],
)
def test_el_sentido_del_ajuste_debe_coincidir_con_su_motivo(motivo, resta, lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido):
        registrar_movimiento(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            cantidad=3,
            usuario=gerente,
            ubicacion_origen=bodega if resta else None,
            ubicacion_destino=None if resta else bodega,
            motivo_ajuste=motivo,
            observacion="Sentido contrario al motivo",
        )


@pytest.mark.parametrize("ubicaciones", ["ninguna", "ambas"])
def test_el_ajuste_lleva_una_sola_ubicacion(ubicaciones, lote, bodega, tunel, gerente):
    recibir(lote, bodega, 50, gerente)
    with pytest.raises(MovimientoInvalido, match="una sola ubicación"):
        registrar_movimiento(
            lote=lote,
            tipo="AJUSTE_CONTEO",
            cantidad=3,
            usuario=gerente,
            ubicacion_origen=bodega if ubicaciones == "ambas" else None,
            ubicacion_destino=tunel if ubicaciones == "ambas" else None,
            motivo_ajuste="OTRO",
            observacion="Debe llevar solo un lado",
        )


# --- Consulta y concurrencia -------------------------------------------------


def test_existencia_de_devuelve_cero_si_nunca_hubo(lote, bodega):
    assert existencia_de(lote, bodega) == Decimal("0")


def test_mover_inventario_bloquea_el_lote_y_su_existencia(lote, bodega, gerente):
    recibir(lote, bodega, 50, gerente)
    with CaptureQueriesContext(connection) as consultas:
        registrar_movimiento(
            lote=lote,
            tipo="DESPACHO_MAYORISTA",
            cantidad=5,
            usuario=gerente,
            ubicacion_origen=bodega,
        )
    bloqueos = [c["sql"] for c in consultas if "FOR UPDATE" in c["sql"]]
    assert any('FROM "lote"' in sql for sql in bloqueos)
    assert any('FROM "existencia"' in sql for sql in bloqueos)
