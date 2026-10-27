"""Traslado a punto de venta: envío, verificación, aceptación, rechazo y reenvío
(RF-38 a RF-45, RN-28, RN-29, RN-30, RD-04)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.accounts.models import Perfil, Usuario
from apps.auditoria.models import Auditoria
from apps.despacho.consultas import candidatos_traslado
from apps.despacho.models import TrasladoPdv, TrasladoPdvObservacion
from apps.despacho.servicios import (
    DespachoInvalido,
    aceptar_traslado,
    agregar_observacion,
    rechazar_traslado,
)
from apps.despacho.tests.conftest import pesos_de
from apps.embultaje.consultas import candidatos_fifo
from apps.inventario.models import Movimiento
from apps.inventario.servicios import existencia_de
from apps.maestros.models import Ubicacion
from apps.puntoventa.models import MovimientoPuntoVenta
from apps.puntoventa.servicios import existencia_pdv


@pytest.fixture
def enviado(enviar):
    return enviar()


def aceptar(traslado, usuario, pesos=None, nombre_coincide=True):
    return aceptar_traslado(
        traslado=traslado,
        usuario=usuario,
        nombre_coincide=nombre_coincide,
        verificadas=pesos if pesos is not None else pesos_de(traslado),
    )


# --- Envío -------------------------------------------------------------------


def test_enviar_no_mueve_la_existencia_y_queda_visible(enviado, en_bultos, zona_bultos):
    """RF-38, RF-39 y RN-30: hasta que el PDV acepte, no se mueve nada."""
    assert enviado.estado == "ENVIADO"
    assert enviado.consecutivo == f"T-{enviado.pk:06d}"
    assert existencia_de(en_bultos, zona_bultos) == Decimal("100")
    assert not Movimiento.objects.filter(tipo="TRASLADO_PDV").exists()
    assert Auditoria.objects.filter(entidad="traslado_pdv", registro_id=enviado.pk).exists()


def test_lo_enviado_queda_apartado(enviado, zona_bultos, producto):
    """Lo que va en camino no se ofrece a otro traslado ni a un pedido."""
    (candidato,) = candidatos_traslado(zona_bultos)
    assert candidato.disponible == Decimal("70")
    assert [c.disponible for c in candidatos_fifo(producto)] == [Decimal("70")]


def test_no_se_envia_lo_que_esta_comprometido_en_un_pedido(enviar, alistar):
    alistar("60")
    with pytest.raises(DespachoInvalido, match="solo hay 40.00 kg disponibles"):
        enviar("50")


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"lineas": []}, "al menos un lote"),
        ({"nombre_entrega": "  "}, "quien entrega"),
    ],
)
def test_el_documento_exige_lotes_y_quien_entrega(enviar, cambios, mensaje):
    with pytest.raises(DespachoInvalido, match=mensaje):
        enviar(**cambios)


def test_un_lote_va_una_sola_vez(enviar, en_bultos):
    lineas = [{"lote": en_bultos, "cantidad": "10"}] * 2
    with pytest.raises(DespachoInvalido, match="una sola vez"):
        enviar(lineas=lineas)


def test_el_destino_es_un_punto_de_venta_y_el_origen_una_zona_de_salida(enviar, bodega, db):
    with pytest.raises(DespachoInvalido, match="punto de venta activo"):
        enviar(destino=bodega)
    zona = Ubicacion.objects.create(
        codigo="TRF-01", nombre="Zona de transformación", tipo="ZONA_TRANSFORMACION"
    )
    with pytest.raises(DespachoInvalido, match="sale de la zona de bultos"):
        enviar(origen=zona)


@pytest.mark.parametrize("perfil", ["consulta", "admin_pdv"])
def test_solo_bodega_envia(request, enviar, perfil):
    with pytest.raises(PermissionDenied):
        enviar(usuario=request.getfixturevalue(perfil))


# --- Aceptar -----------------------------------------------------------------


def test_aceptar_mueve_de_bodega_al_pdv_en_una_transaccion(
    enviado, admin_pdv, en_bultos, zona_bultos, punto_venta, producto
):
    """RF-42 y RN-30: sale por lote de bodega y entra por producto al PDV."""
    aceptar(enviado, admin_pdv)

    enviado.refresh_from_db()
    assert enviado.estado == "ACEPTADO"
    assert enviado.usuario_confirma == admin_pdv
    assert existencia_de(en_bultos, zona_bultos) == Decimal("70")
    assert existencia_pdv(producto, punto_venta) == Decimal("30")
    salida = Movimiento.objects.get(tipo="TRASLADO_PDV")
    assert (salida.ubicacion_origen, salida.ubicacion_destino) == (zona_bultos, punto_venta)
    entrada = MovimientoPuntoVenta.objects.get()
    assert (entrada.tipo, entrada.cantidad) == ("ENTRADA_TRASLADO", Decimal("30"))
    assert enviado.detalles.get().cantidad_verificada == Decimal("30")


def test_el_gerente_tambien_puede_aceptar(enviado, gerente, producto, punto_venta):
    aceptar(enviado, gerente)
    assert existencia_pdv(producto, punto_venta) == Decimal("30")


def test_si_quien_entrega_no_coincide_no_se_acepta(enviado, admin_pdv):
    """RF-41: la identidad de quien entrega se verifica antes de aceptar."""
    with pytest.raises(DespachoInvalido, match="rechace el traslado"):
        aceptar(enviado, admin_pdv, nombre_coincide=False)


def test_si_un_peso_no_coincide_no_se_acepta_ni_se_mueve_nada(
    enviado, admin_pdv, en_bultos, zona_bultos, producto, punto_venta
):
    """RN-28: una sola línea distinta obliga a rechazar el documento completo."""
    with pytest.raises(DespachoInvalido, match="no coincide en L-000001"):
        aceptar(enviado, admin_pdv, pesos_de(enviado, {"L-000001": "29.5"}))
    assert existencia_de(en_bultos, zona_bultos) == Decimal("100")
    assert existencia_pdv(producto, punto_venta) == Decimal("0")
    enviado.refresh_from_db()
    assert enviado.estado == "ENVIADO"


def test_hay_que_pesar_todas_las_lineas(enviado, admin_pdv):
    with pytest.raises(DespachoInvalido, match="todas las líneas"):
        aceptar(enviado, admin_pdv, pesos={})


def test_solo_decide_el_pdv_destino_o_el_gerente(enviado, jefe_bodega, db):
    """RN-06: un administrador de otro punto no recibe lo que no es suyo."""
    otro_punto = Ubicacion.objects.create(
        codigo="PDV-02", nombre="Punto de venta 2", tipo="PUNTO_VENTA"
    )
    otro = Usuario.objects.create_user(
        "otro_pdv",
        "ClaveSegura123",
        nombre_completo="Otro administrador",
        perfil=Perfil.objects.get(codigo="ADMIN_PDV"),
        ubicacion=otro_punto,
    )
    for usuario in (otro, jefe_bodega):
        with pytest.raises(PermissionDenied):
            aceptar(enviado, usuario)


def test_un_traslado_se_decide_una_sola_vez(enviado, admin_pdv):
    aceptar(enviado, admin_pdv)
    with pytest.raises(DespachoInvalido, match="ya fue aceptado"):
        aceptar(enviado, admin_pdv)
    with pytest.raises(DespachoInvalido, match="ya fue aceptado"):
        rechazar_traslado(traslado=enviado, usuario=admin_pdv, observacion="Tarde")


# --- Rechazar y reenviar -----------------------------------------------------


def test_rechazar_exige_motivo_y_no_mueve_nada(
    enviado, admin_pdv, en_bultos, zona_bultos, producto
):
    """RF-43 y RN-29."""
    with pytest.raises(DespachoInvalido, match="motivo del rechazo"):
        rechazar_traslado(traslado=enviado, usuario=admin_pdv, observacion=" ")

    rechazar_traslado(
        traslado=enviado,
        usuario=admin_pdv,
        observacion="Llegaron 29,5 kg",
        verificadas=pesos_de(enviado, {"L-000001": "29.5"}),
    )

    enviado.refresh_from_db()
    assert enviado.estado == "RECHAZADO"
    assert enviado.detalles.get().cantidad_verificada == Decimal("29.50")
    assert enviado.observaciones.get().observacion == "Llegaron 29,5 kg"
    assert existencia_de(en_bultos, zona_bultos) == Decimal("100")
    assert not MovimientoPuntoVenta.objects.exists()
    # Lo rechazado vuelve a estar disponible para corregir y reenviar.
    assert [c.disponible for c in candidatos_fifo(producto)] == [Decimal("100")]


def test_el_reenvio_queda_ligado_al_rechazado_una_sola_vez(enviado, enviar, admin_pdv):
    """RF-44 y RF-45: el ciclo se repite hasta que el PDV acepte."""
    rechazar_traslado(traslado=enviado, usuario=admin_pdv, observacion="Peso distinto")
    reenvio = enviar("29.5", traslado_anterior=enviado)
    assert reenvio.traslado_anterior == enviado
    assert list(enviado.reenvios.all()) == [reenvio]

    with pytest.raises(DespachoInvalido, match="ya tiene su reenvío"):
        enviar("29.5", traslado_anterior=enviado)
    aceptar(reenvio, admin_pdv)


def test_solo_se_reenvia_un_rechazado(enviado, enviar):
    with pytest.raises(DespachoInvalido, match="Solo se reenvía un traslado rechazado"):
        enviar("10", traslado_anterior=enviado)


def test_las_observaciones_son_de_quien_participa(enviado, admin_pdv, consulta):
    agregar_observacion(traslado=enviado, usuario=admin_pdv, observacion="Llega a las 3 p. m.")
    assert TrasladoPdvObservacion.objects.count() == 1
    with pytest.raises(PermissionDenied):
        agregar_observacion(traslado=enviado, usuario=consulta, observacion="Hola")


# --- Restricciones de la base ------------------------------------------------


def test_la_base_exige_quien_y_cuando_decide(enviado):
    with pytest.raises(IntegrityError), transaction.atomic():
        TrasladoPdv.objects.filter(pk=enviado.pk).update(estado="ACEPTADO")


def test_la_base_no_admite_dos_reenvios_del_mismo_rechazo(enviado, enviar, admin_pdv):
    rechazar_traslado(traslado=enviado, usuario=admin_pdv, observacion="Peso distinto")
    reenvio = enviar("10", traslado_anterior=enviado)
    otro = enviar("10")
    with pytest.raises(IntegrityError), transaction.atomic():
        TrasladoPdv.objects.filter(pk=otro.pk).update(traslado_anterior=enviado)
    assert reenvio.traslado_anterior_id == enviado.pk
