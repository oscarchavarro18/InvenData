"""Servicio de embultaje y cierre del lote (RF-30, RF-31, RN-23, RN-24, RN-26)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Auditoria
from apps.embultaje.models import DocumentoEmbultaje, EmbultajeRegistro
from apps.embultaje.servicios import EmbultajeInvalido, cerrar_lote
from apps.inventario.models import Lote, Movimiento
from apps.inventario.servicios import ExistenciaInsuficiente, existencia_de, registrar_movimiento
from apps.maestros.models import Ubicacion
from apps.transformacion.servicios import TransformacionInvalida, crear_orden

# --- Registrar ---------------------------------------------------------------


def test_por_bultos_mueve_el_total_y_genera_bultos_numerados(
    embultar, en_bodega, bodega, zona_bultos
):
    """RN-26, RF-30, RF-31: cantidad × peso, un bulto por cada uno, vencimiento heredado."""
    registro = embultar(usa_calculo_bultos=True, cantidad_bultos=3, peso_por_bulto="25.50")

    assert registro.total_kilos == Decimal("76.50")
    assert existencia_de(en_bodega, bodega) == Decimal("23.50")
    assert existencia_de(en_bodega, zona_bultos) == Decimal("76.50")
    movimiento = Movimiento.objects.get(tipo="EMBULTAJE")
    assert (movimiento.ubicacion_origen, movimiento.ubicacion_destino) == (bodega, zona_bultos)
    assert movimiento.cantidad == Decimal("76.50")

    bultos = list(registro.bultos.all())
    assert len(bultos) == 3
    for bulto in bultos:
        assert bulto.consecutivo == f"B-{bulto.pk:06d}"
        assert bulto.peso == Decimal("25.50")
        assert bulto.fecha_vencimiento == en_bodega.fecha_vencimiento
        assert bulto.rotulo_impreso is False


def test_con_el_total_digitado_no_genera_bultos(embultar):
    registro = embultar(total_kilos="40")
    assert registro.total_kilos == Decimal("40")
    assert registro.usa_calculo_bultos is False
    assert not registro.bultos.exists()


def test_los_registros_del_dia_van_al_mismo_documento(embultar, jefe_bodega):
    """SN-22: el documento es del día; se crea con el primer registro."""
    primero = embultar(total_kilos="10")
    segundo = embultar(total_kilos="15")
    documento = DocumentoEmbultaje.objects.get()
    assert documento.fecha == timezone.localdate()
    assert documento.usuario == jefe_bodega
    assert {primero.documento_embultaje_id, segundo.documento_embultaje_id} == {documento.pk}


def test_el_registro_queda_en_auditoria(embultar):
    registro = embultar(usa_calculo_bultos=True, cantidad_bultos=2, peso_por_bulto="10")
    auditoria = Auditoria.objects.get(entidad="embultaje_registro")
    assert auditoria.registro_id == registro.pk
    assert auditoria.accion == AccionAuditoria.CREAR
    assert auditoria.valor_nuevo["total_kilos"] == "20.00"


@pytest.mark.parametrize(
    "datos",
    [
        {"usa_calculo_bultos": True, "peso_por_bulto": "25"},  # sin cantidad
        {"usa_calculo_bultos": True, "cantidad_bultos": "2.5", "peso_por_bulto": "25"},
        {"usa_calculo_bultos": True, "cantidad_bultos": 0, "peso_por_bulto": "25"},
        {"usa_calculo_bultos": True, "cantidad_bultos": 2, "peso_por_bulto": "-1"},
        {"total_kilos": "10", "cantidad_bultos": 2},  # digitado con bultos
        {},  # digitado sin total
        {"total_kilos": "1.234"},
    ],
)
def test_los_datos_del_modo_deben_ser_coherentes(embultar, datos):
    with pytest.raises(EmbultajeInvalido):
        embultar(**datos)
    assert not EmbultajeRegistro.objects.exists()


def test_no_se_embulta_mas_de_lo_que_hay_ni_queda_nada_a_medias(embultar, en_bodega, bodega):
    """RN-16: ni registro, ni documento, ni bultos si el saldo no alcanza."""
    with pytest.raises(ExistenciaInsuficiente):
        embultar(usa_calculo_bultos=True, cantidad_bultos=5, peso_por_bulto="25")
    assert existencia_de(en_bodega, bodega) == Decimal("100")
    assert not DocumentoEmbultaje.objects.exists()
    assert not EmbultajeRegistro.objects.exists()


def test_no_se_embulta_desde_donde_no_hay_existencia(embultar, tunel):
    """RN-23: el lote debe tener existencia en la ubicación de origen."""
    with pytest.raises(EmbultajeInvalido, match="no tiene existencia"):
        embultar(ubicacion_origen=tunel, total_kilos="1")


def test_un_lote_cerrado_no_admite_nuevos_embultajes(embultar, en_bodega):
    """RN-23: solo lotes DISPONIBLE."""
    Lote.objects.filter(pk=en_bodega.pk).update(estado="EMBULTADO")
    with pytest.raises(EmbultajeInvalido, match="ya se cerró"):
        embultar(total_kilos="10")


def test_un_lote_de_transformacion_no_se_embulta(embultar, en_bodega, datos_lote, bodega, gerente):
    """RN-24: lo que sale de una transformación no pasa por embultaje."""
    derivado = Lote.objects.create(
        codigo="L-DER", origen="TRANSFORMACION", lote_origen=en_bodega, **datos_lote
    )
    registrar_movimiento(
        lote=derivado,
        tipo="PRODUCCION_TRANSFORMACION",
        cantidad="10",
        usuario=gerente,
        ubicacion_destino=bodega,
    )
    with pytest.raises(EmbultajeInvalido, match="viene de una transformación"):
        embultar(lote=derivado, total_kilos="5")


def test_un_lote_ya_transformado_no_se_embulta(embultar, en_bodega, bodega, gerente):
    """RN-24: transformar y embultar son caminos excluyentes."""
    registrar_movimiento(
        lote=en_bodega,
        tipo="CONSUMO_TRANSFORMACION",
        cantidad="10",
        usuario=gerente,
        ubicacion_origen=bodega,
    )
    with pytest.raises(EmbultajeInvalido, match="ya se transformó"):
        embultar(total_kilos="5")


def test_un_lote_embultado_ya_no_se_transforma(embultar, en_bodega, bodega, jefe_bodega):
    """RN-24 desde el otro lado: M4 rechaza un lote que ya pasó por embultaje."""
    en_bodega.producto.admite_transformacion = True
    en_bodega.producto.save()
    embultar(total_kilos="10")
    with pytest.raises(TransformacionInvalida, match="embultaje"):
        crear_orden(
            lote=en_bodega, ubicacion_origen=bodega, cantidad_consumida="5", usuario=jefe_bodega
        )


def test_la_zona_de_bultos_no_es_origen(embultar, en_bodega, bodega, zona_bultos, tunel):
    embultar(total_kilos="10")
    with pytest.raises(EmbultajeInvalido, match="ya está embultado"):
        embultar(ubicacion_origen=zona_bultos, ubicacion_destino=tunel, total_kilos="5")


@pytest.mark.parametrize("destino", ["punto_venta", "inactiva", "misma"])
def test_el_destino_debe_ser_otra_zona_de_bodega_activa(request, embultar, bodega, destino):
    if destino == "misma":
        ubicacion = bodega
    elif destino == "inactiva":
        ubicacion = Ubicacion.objects.create(
            codigo="BUL-99", nombre="Bultos vieja", tipo="ZONA_BULTOS", activo=False
        )
    else:
        ubicacion = request.getfixturevalue("punto_venta")
    with pytest.raises(EmbultajeInvalido):
        embultar(ubicacion_destino=ubicacion, total_kilos="5")


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_gerente_y_jefe_de_bodega_embultan(request, embultar, perfil):
    with pytest.raises(PermissionDenied):
        embultar(usuario=request.getfixturevalue(perfil), total_kilos="5")


# --- Cerrar el lote ----------------------------------------------------------


def test_cerrar_da_de_baja_el_residuo_y_congela_la_foto(
    embultar, en_bodega, bodega, zona_bultos, jefe_bodega
):
    """El residuo en origen es la merma de embultaje; lo embultado se conserva."""
    embultar(usa_calculo_bultos=True, cantidad_bultos=3, peso_por_bulto="25")
    embultar(total_kilos="20")

    lote = cerrar_lote(lote=en_bodega, usuario=jefe_bodega)

    assert lote.estado == "EMBULTADO"
    assert lote.total_embultado_kg == Decimal("95")
    assert lote.merma_vs_origen_kg == Decimal("5")
    assert lote.cerrado_por == jefe_bodega
    assert lote.cerrado_en is not None
    assert existencia_de(lote, bodega) == Decimal("0")
    assert existencia_de(lote, zona_bultos) == Decimal("95")
    merma = Movimiento.objects.get(tipo="MERMA_EMBULTAJE")
    assert (merma.ubicacion_origen, merma.cantidad) == (bodega, Decimal("5"))
    auditoria = Auditoria.objects.get(entidad="lote", accion=AccionAuditoria.MODIFICAR)
    assert auditoria.valor_anterior["estado"] == "DISPONIBLE"
    assert auditoria.valor_nuevo["estado"] == "EMBULTADO"


def test_si_se_embulto_todo_la_merma_es_cero(embultar, en_bodega, jefe_bodega):
    embultar(total_kilos="100")
    lote = cerrar_lote(lote=en_bodega, usuario=jefe_bodega)
    assert lote.merma_vs_origen_kg == Decimal("0")
    assert not Movimiento.objects.filter(tipo="MERMA_EMBULTAJE").exists()


def test_no_se_cierra_un_lote_sin_embultajes(en_bodega, jefe_bodega):
    with pytest.raises(EmbultajeInvalido, match="no tiene embultajes"):
        cerrar_lote(lote=en_bodega, usuario=jefe_bodega)


def test_no_se_cierra_con_producto_sin_embultar_en_otra_zona(
    embultar, en_bodega, bodega, tunel, jefe_bodega, gerente
):
    """Lo que está en una zona que no fue origen ni destino no es merma: impide cerrar."""
    registrar_movimiento(
        lote=en_bodega,
        tipo="TRASLADO_INTERNO",
        cantidad="30",
        usuario=gerente,
        ubicacion_origen=bodega,
        ubicacion_destino=tunel,
    )
    embultar(total_kilos="50")
    with pytest.raises(EmbultajeInvalido, match="sin embultar en Túnel"):
        cerrar_lote(lote=en_bodega, usuario=jefe_bodega)
    en_bodega.refresh_from_db()
    assert en_bodega.estado == "DISPONIBLE"
    assert existencia_de(en_bodega, bodega) == Decimal("20")


def test_un_lote_cerrado_no_se_cierra_otra_vez(embultar, en_bodega, jefe_bodega):
    embultar(total_kilos="90")
    cerrar_lote(lote=en_bodega, usuario=jefe_bodega)
    with pytest.raises(EmbultajeInvalido, match="ya está cerrado"):
        cerrar_lote(lote=en_bodega, usuario=jefe_bodega)
    with pytest.raises(EmbultajeInvalido, match="ya se cerró"):
        embultar(total_kilos="1")


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_gerente_y_jefe_de_bodega_cierran(request, embultar, en_bodega, perfil):
    embultar(total_kilos="90")
    with pytest.raises(PermissionDenied):
        cerrar_lote(lote=en_bodega, usuario=request.getfixturevalue(perfil))
