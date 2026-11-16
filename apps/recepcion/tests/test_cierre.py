from datetime import date
from decimal import Decimal

import pytest

from apps.inventario.models import Existencia, Lote, Movimiento
from apps.inventario.servicios import existencia_de, reversar_movimiento
from apps.maestros.models import Producto
from apps.recepcion import servicios
from apps.recepcion.models import DocumentoProveedorLinea, Recepcion
from apps.recepcion.servicios import (
    RecepcionInvalida,
    cerrar_documento,
    crear_lote_recepcion,
    eliminar_lote_sin_pesadas,
    registrar_pesada,
)


@pytest.fixture
def documento(linea):
    return linea.documento_proveedor


@pytest.fixture
def pesar(canastilla, jefe_bodega, tunel):
    """Pesa una tanda de 37.50 kg netos (5 canastillas, 50 kg brutos) en el túnel."""

    def _pesar(lote, **cambios):
        datos = {
            "lote": lote,
            "tipo_embalaje": canastilla,
            "cantidad_embalajes": 5,
            "peso_bruto": Decimal("50.00"),
            "temperatura": Decimal("3.00"),
            "ubicacion_destino": tunel,
            "usuario": jefe_bodega,
        }
        return registrar_pesada(**{**datos, **cambios})

    return _pesar


# --- El cierre afecta las existencias -------------------------------------------


def test_cerrar_deja_el_documento_cerrado(documento, lote, pesar, gerente):
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    documento.refresh_from_db()
    assert documento.estado == "CERRADO"


def test_cerrar_crea_la_existencia_con_la_suma_de_las_tandas(
    documento, lote, pesar, tunel, gerente
):
    pesar(lote)
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    assert existencia_de(lote, tunel) == Decimal("75.00")


def test_dos_tandas_a_la_misma_ubicacion_dan_un_solo_movimiento(documento, lote, pesar, gerente):
    pesar(lote)
    pesar(lote)
    movimientos = cerrar_documento(documento=documento, usuario=gerente)
    assert len(movimientos) == 1
    assert movimientos[0].cantidad == Decimal("75.00")


def test_el_movimiento_es_de_recepcion_sin_origen(documento, lote, pesar, tunel, gerente):
    pesar(lote)
    (movimiento,) = cerrar_documento(documento=documento, usuario=gerente)
    assert movimiento.tipo == "RECEPCION"
    assert movimiento.lote == lote
    assert movimiento.ubicacion_origen is None
    assert movimiento.ubicacion_destino == tunel
    assert movimiento.usuario == gerente


def test_tandas_a_ubicaciones_distintas_dan_un_movimiento_por_ubicacion(
    documento, lote, pesar, tunel, bodega, gerente
):
    pesar(lote)
    pesar(lote, ubicacion_destino=bodega)
    movimientos = cerrar_documento(documento=documento, usuario=gerente)
    assert len(movimientos) == 2
    assert existencia_de(lote, tunel) == Decimal("37.50")
    assert existencia_de(lote, bodega) == Decimal("37.50")


def test_varios_lotes_de_la_misma_linea(documento, linea, lote, pesar, gerente):
    segundo = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 15)
    )
    pesar(lote)
    pesar(segundo)
    movimientos = cerrar_documento(documento=documento, usuario=gerente)
    assert {m.lote for m in movimientos} == {lote, segundo}
    linea.refresh_from_db()
    assert linea.cantidad_recibida == Decimal("75.00")


# --- Las líneas congelan lo recibido y la diferencia -----------------------------


def test_la_linea_congela_lo_recibido_y_la_diferencia(documento, linea, lote, pesar, gerente):
    pesar(lote)  # 37.50 de 100 declarados
    cerrar_documento(documento=documento, usuario=gerente)
    linea.refresh_from_db()
    assert linea.cantidad_recibida == Decimal("37.50")
    assert linea.diferencia_kg == Decimal("62.50")


def test_si_llega_mas_de_lo_declarado_la_diferencia_es_negativa(
    documento, linea, lote, pesar, gerente
):
    linea.cantidad = Decimal("30")
    linea.save()
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    linea.refresh_from_db()
    assert linea.diferencia_kg == Decimal("-7.50")


def test_una_linea_que_no_llego_queda_con_cero_recibido(documento, linea, lote, pesar, gerente):
    categoria = linea.producto.categoria
    otro = Producto.objects.create(
        codigo="PES-001", nombre="Tilapia", unidad_medida="KG", categoria=categoria
    )
    ausente = DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=otro, cantidad=Decimal("40")
    )
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    ausente.refresh_from_db()
    assert ausente.cantidad_recibida == Decimal("0")
    assert ausente.diferencia_kg == Decimal("40")


def test_cada_linea_recibe_solo_lo_suyo(documento, linea, lote, pesar, gerente):
    otro = Producto.objects.create(
        codigo="PES-001", nombre="Tilapia", unidad_medida="KG", categoria=linea.producto.categoria
    )
    otra = DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=otro, cantidad=Decimal("40")
    )
    lote_otra = Lote.objects.create(
        codigo="L-OTRA",
        origen="RECEPCION",
        documento_proveedor_linea=otra,
        producto=otro,
        estado_producto="FRESCO",
        fecha_vencimiento=date(2026, 12, 1),
    )
    pesar(lote)
    pesar(lote_otra)
    pesar(lote_otra)
    cerrar_documento(documento=documento, usuario=gerente)
    linea.refresh_from_db()
    otra.refresh_from_db()
    assert linea.cantidad_recibida == Decimal("37.50")
    assert otra.cantidad_recibida == Decimal("75.00")
    assert otra.diferencia_kg == Decimal("-35.00")


def test_reversar_el_movimiento_no_cambia_lo_congelado(documento, linea, lote, pesar, gerente):
    pesar(lote)
    (movimiento,) = cerrar_documento(documento=documento, usuario=gerente)
    reversar_movimiento(movimiento=movimiento, usuario=gerente, observacion="Se pesó mal")
    linea.refresh_from_db()
    assert linea.cantidad_recibida == Decimal("37.50")
    assert linea.diferencia_kg == Decimal("62.50")


# --- Reglas que impiden cerrar ----------------------------------------------------


def test_un_documento_cerrado_no_se_vuelve_a_cerrar(documento, lote, pesar, tunel, gerente):
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        cerrar_documento(documento=documento, usuario=gerente)
    assert Movimiento.objects.count() == 1
    assert existencia_de(lote, tunel) == Decimal("37.50")


def test_no_se_cierra_un_documento_sin_lineas(documento, gerente):
    documento.lineas.all().delete()
    with pytest.raises(RecepcionInvalida, match="no tiene líneas"):
        cerrar_documento(documento=documento, usuario=gerente)


def test_no_se_cierra_un_documento_sin_pesadas(documento, gerente):
    with pytest.raises(RecepcionInvalida, match="sin ninguna pesada"):
        cerrar_documento(documento=documento, usuario=gerente)
    documento.refresh_from_db()
    assert documento.estado == "ABIERTO"


def test_no_se_cierra_con_un_lote_sin_pesadas(documento, linea, lote, pesar, gerente):
    sin_pesar = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 15)
    )
    pesar(lote)
    with pytest.raises(RecepcionInvalida, match=sin_pesar.codigo):
        cerrar_documento(documento=documento, usuario=gerente)
    assert Movimiento.objects.count() == 0


def test_eliminar_el_lote_sin_pesadas_permite_cerrar(documento, linea, lote, pesar, gerente):
    sin_pesar = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 15)
    )
    pesar(lote)
    eliminar_lote_sin_pesadas(lote=sin_pesar)
    cerrar_documento(documento=documento, usuario=gerente)
    assert not Lote.objects.filter(pk=sin_pesar.pk).exists()


def test_si_algo_falla_no_queda_nada_a_medias(
    documento, linea, lote, pesar, bodega, gerente, monkeypatch
):
    pesar(lote)
    pesar(lote, ubicacion_destino=bodega)
    original = servicios.registrar_movimiento
    llamadas = []

    def falla_en_la_segunda(**datos):
        llamadas.append(datos)
        if len(llamadas) == 2:
            raise RuntimeError("falla simulada")
        return original(**datos)

    monkeypatch.setattr(servicios, "registrar_movimiento", falla_en_la_segunda)
    with pytest.raises(RuntimeError):
        cerrar_documento(documento=documento, usuario=gerente)

    documento.refresh_from_db()
    linea.refresh_from_db()
    assert documento.estado == "ABIERTO"
    assert linea.cantidad_recibida is None
    assert Movimiento.objects.count() == 0
    assert Existencia.objects.count() == 0


# --- Después de cerrar ------------------------------------------------------------


def test_cerrado_el_documento_no_se_puede_seguir_pesando(documento, lote, pesar, gerente):
    pesar(lote)
    cerrar_documento(documento=documento, usuario=gerente)
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        pesar(lote)
    assert Recepcion.objects.count() == 1


# --- eliminar_lote_sin_pesadas -----------------------------------------------------


def test_eliminar_un_lote_sin_pesadas(linea):
    lote = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    eliminar_lote_sin_pesadas(lote=lote)
    assert Lote.objects.count() == 0


def test_no_se_elimina_un_lote_con_pesadas(lote, pesar):
    pesar(lote)
    with pytest.raises(RecepcionInvalida, match="ya tiene pesadas"):
        eliminar_lote_sin_pesadas(lote=lote)
    assert Lote.objects.filter(pk=lote.pk).exists()


def test_no_se_elimina_un_lote_de_un_documento_cerrado(documento, linea):
    sin_pesar = crear_lote_recepcion(
        linea=linea, estado_producto="FRESCO", fecha_vencimiento=date(2026, 12, 1)
    )
    documento.estado = "CERRADO"
    documento.save()
    with pytest.raises(RecepcionInvalida, match="cerrado"):
        eliminar_lote_sin_pesadas(lote=sin_pesar)


def test_no_se_elimina_un_lote_que_no_viene_de_recepcion(datos_lote):
    otro = Lote.objects.create(codigo="LI-1", origen="INVENTARIO_INICIAL", **datos_lote)
    with pytest.raises(RecepcionInvalida, match="recepción"):
        eliminar_lote_sin_pesadas(lote=otro)
