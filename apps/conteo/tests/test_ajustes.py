"""Ajustes manuales y reversos del Gerente en bodega y en punto de venta
(RF-09, RF-53, RN-17, RN-32, RN-34, RN-35)."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.conteo.servicios import (
    ConteoInvalido,
    ajustar_bodega,
    ajustar_pdv,
    reversar_bodega,
    reversar_pdv,
)
from apps.inventario.models import Movimiento
from apps.inventario.servicios import MovimientoInvalido, existencia_de, trasladar_entre_zonas
from apps.puntoventa.models import MovimientoPuntoVenta
from apps.puntoventa.servicios import (
    ExistenciaPdvInsuficiente,
    MovimientoPdvInvalido,
    existencia_pdv,
    registrar_venta_consumidor,
)


def ajuste_bodega(lote, ubicacion, usuario, sentido="SALIDA", cantidad="5", motivo="PERDIDA"):
    return ajustar_bodega(
        lote=lote,
        ubicacion=ubicacion,
        sentido=sentido,
        cantidad=cantidad,
        motivo=motivo,
        observacion="Canastilla rota",
        usuario=usuario,
    )


def ajuste_pdv(
    punto,
    producto,
    usuario,
    sentido="SALIDA",
    cantidad="5",
    motivo="VENCIMIENTO",
    observacion="Se venció en vitrina",
):
    return ajustar_pdv(
        ubicacion=punto,
        producto=producto,
        sentido=sentido,
        cantidad=cantidad,
        motivo=motivo,
        observacion=observacion,
        usuario=usuario,
    )


# --- Ajustes en bodega -------------------------------------------------------


def test_el_gerente_ajusta_la_bodega_con_su_motivo(en_bodega, bodega, gerente):
    """RF-53: la pérdida resta y queda justificada y auditada."""
    movimiento = ajuste_bodega(en_bodega, bodega, gerente)
    assert existencia_de(en_bodega, bodega) == Decimal("25")
    assert (movimiento.motivo_ajuste, movimiento.ubicacion_origen) == ("PERDIDA", bodega)
    assert Auditoria.objects.filter(entidad="movimiento", registro_id=movimiento.pk).exists()


def test_un_sobrante_suma_en_bodega(en_bodega, bodega, gerente):
    ajuste_bodega(en_bodega, bodega, gerente, sentido="ENTRADA", motivo="SOBRANTE")
    assert existencia_de(en_bodega, bodega) == Decimal("35")


def test_solo_el_gerente_ajusta_la_bodega(en_bodega, bodega, jefe_bodega):
    """RN-34."""
    with pytest.raises(PermissionDenied):
        ajuste_bodega(en_bodega, bodega, jefe_bodega)


def test_el_sentido_debe_cuadrar_con_el_motivo_en_bodega(en_bodega, bodega, gerente):
    with pytest.raises(MovimientoInvalido, match="resta"):
        ajuste_bodega(en_bodega, bodega, gerente, sentido="ENTRADA", motivo="PERDIDA")
    with pytest.raises(ConteoInvalido, match="suma o resta"):
        ajuste_bodega(en_bodega, bodega, gerente, sentido="DE LADO")


# --- Ajustes en el punto de venta --------------------------------------------


def test_el_gerente_ajusta_el_pdv(en_punto, punto_venta, gerente):
    """RF-53 y RN-32: también en el punto de venta, con sentido, motivo y observación."""
    movimiento = ajuste_pdv(punto_venta, en_punto, gerente)
    assert existencia_pdv(en_punto, punto_venta) == Decimal("15")
    assert (movimiento.tipo, movimiento.sentido) == ("AJUSTE_CONTEO", "SALIDA")
    assert Auditoria.objects.filter(
        entidad="movimiento_punto_venta", registro_id=movimiento.pk
    ).exists()


def test_un_error_de_conteo_puede_sumar_en_el_pdv(en_punto, punto_venta, gerente):
    ajuste_pdv(punto_venta, en_punto, gerente, sentido="ENTRADA", motivo="ERROR_CONTEO")
    assert existencia_pdv(en_punto, punto_venta) == Decimal("25")


def test_el_administrador_del_pdv_no_ajusta_su_punto(en_punto, punto_venta, admin_pdv):
    """RN-32: aunque esté asignado a esa ubicación."""
    with pytest.raises(PermissionDenied):
        ajuste_pdv(punto_venta, en_punto, admin_pdv)


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"sentido": "ENTRADA", "motivo": "VENCIMIENTO"}, "resta"),
        ({"sentido": "SALIDA", "motivo": "SOBRANTE"}, "suma"),
        ({"motivo": "INVENTADO"}, "motivo de la lista"),
        ({"observacion": "  "}, "observación"),
    ],
)
def test_el_ajuste_del_pdv_debe_ser_coherente(en_punto, punto_venta, gerente, cambios, mensaje):
    with pytest.raises(MovimientoPdvInvalido, match=mensaje):
        ajuste_pdv(punto_venta, en_punto, gerente, **cambios)


def test_un_ajuste_no_deja_la_existencia_negativa(en_punto, punto_venta, gerente):
    with pytest.raises(ExistenciaPdvInsuficiente):
        ajuste_pdv(punto_venta, en_punto, gerente, cantidad="20.01")


@pytest.mark.parametrize(
    "cambios",
    [{"sentido": "ENTRADA", "tipo": "VENTA"}, {"sentido": "ENTRADA", "motivo_ajuste": "PERDIDA"}],
)
def test_la_base_exige_el_sentido_coherente(en_punto, punto_venta, gerente, cambios):
    movimiento = ajuste_pdv(punto_venta, en_punto, gerente)
    with pytest.raises(IntegrityError), transaction.atomic():
        MovimientoPuntoVenta.objects.filter(pk=movimiento.pk).update(**cambios)


# --- Reversos ----------------------------------------------------------------


def test_reversar_una_venta_devuelve_el_producto_sin_borrarla(
    en_punto, punto_venta, admin_pdv, gerente
):
    """RF-09: la venta mal registrada se conserva; el reverso devuelve lo vendido."""
    registrar_venta_consumidor(
        ubicacion=punto_venta,
        numero_factura_siigo="FE-1",
        lineas=[{"producto": en_punto, "cantidad": "8"}],
        usuario=admin_pdv,
    )
    venta = MovimientoPuntoVenta.objects.get(tipo="VENTA")

    reverso = reversar_pdv(movimiento=venta, usuario=gerente, observacion="Factura anulada")

    assert existencia_pdv(en_punto, punto_venta) == Decimal("20")
    assert (reverso.sentido, reverso.motivo_ajuste) == ("ENTRADA", "ERROR_CONTEO")
    assert reverso.movimiento_punto_venta_reversado == venta
    assert MovimientoPuntoVenta.objects.filter(pk=venta.pk).exists()
    with pytest.raises(MovimientoPdvInvalido, match="ya fue reversado"):
        reversar_pdv(movimiento=venta, usuario=gerente, observacion="Otra vez")
    with pytest.raises(MovimientoPdvInvalido, match="no se puede reversar"):
        reversar_pdv(movimiento=reverso, usuario=gerente, observacion="Otra vez")


def test_solo_el_gerente_reversa(en_punto, punto_venta, admin_pdv):
    entrada = MovimientoPuntoVenta.objects.get()
    with pytest.raises(PermissionDenied):
        reversar_pdv(movimiento=entrada, usuario=admin_pdv, observacion="Error")


def test_reversar_un_traslado_interno_en_bodega(en_bodega, bodega, tunel, jefe_bodega, gerente):
    traslado = trasladar_entre_zonas(
        lote=en_bodega, origen=bodega, destino=tunel, cantidad="10", usuario=jefe_bodega
    )
    ajustes = reversar_bodega(movimiento=traslado, usuario=gerente, observacion="Zona equivocada")
    assert existencia_de(en_bodega, bodega) == Decimal("30")
    assert existencia_de(en_bodega, tunel) == Decimal("0")
    assert (
        Auditoria.objects.filter(
            entidad="movimiento", registro_id__in=[a.pk for a in ajustes]
        ).count()
        == 2
    )


# --- Pantallas ---------------------------------------------------------------


def test_el_gerente_ajusta_desde_la_pantalla(client, gerente, en_bodega, bodega):
    client.force_login(gerente)
    url = reverse("conteo:ajuste_bodega", args=[en_bodega.pk, bodega.pk])
    assert "Existencia actual" in client.get(url).content.decode()
    datos = {
        "sentido": "SALIDA",
        "cantidad": "5",
        "motivo": "PERDIDA",
        "observacion": "Canastilla rota",
    }
    respuesta = client.post(url, datos)
    assert respuesta.url == reverse("inventario:lote_detalle", args=[en_bodega.pk])
    assert existencia_de(en_bodega, bodega) == Decimal("25")


def test_un_error_del_ajuste_se_muestra(client, gerente, en_punto, punto_venta):
    client.force_login(gerente)
    url = reverse("conteo:ajuste_pdv") + f"?ubicacion={punto_venta.pk}"
    datos = {
        "producto": en_punto.pk,
        "sentido": "ENTRADA",
        "cantidad": "1",
        "motivo": "PERDIDA",
        "observacion": "x",
    }
    respuesta = client.post(url, datos)
    assert respuesta.status_code == 200
    assert "Un ajuste por PERDIDA resta" in respuesta.content.decode()


def test_reversar_desde_el_historial_del_pdv(client, gerente, en_punto, punto_venta):
    entrada = MovimientoPuntoVenta.objects.get()
    client.force_login(gerente)
    historial = client.get(reverse("puntoventa:historial")).content.decode()
    url = reverse("conteo:reverso_pdv", args=[entrada.pk])
    assert url in historial
    client.post(url, {"observacion": "Traslado duplicado"})
    assert existencia_pdv(en_punto, punto_venta) == Decimal("0")


@pytest.mark.parametrize("perfil", ["jefe_bodega", "admin_pdv", "consulta"])
def test_solo_el_gerente_entra_a_ajustar_o_reversar(
    request, client, perfil, en_bodega, bodega, punto_venta
):
    client.force_login(request.getfixturevalue(perfil))
    movimiento = Movimiento.objects.get()
    urls = [
        reverse("conteo:ajuste_bodega", args=[en_bodega.pk, bodega.pk]),
        reverse("conteo:ajuste_pdv") + f"?ubicacion={punto_venta.pk}",
        reverse("conteo:reverso_bodega", args=[movimiento.pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 403


def test_los_botones_de_reverso_y_ajuste_son_solo_del_gerente(
    client, gerente, jefe_bodega, en_bodega
):
    url_lote = reverse("inventario:lote_detalle", args=[en_bodega.pk])
    client.force_login(gerente)
    assert "Reversar" in client.get(url_lote).content.decode()
    assert "Ajustar" in client.get(reverse("inventario:existencias")).content.decode()
    client.force_login(jefe_bodega)
    assert "Reversar" not in client.get(url_lote).content.decode()
    assert "Ajustar" not in client.get(reverse("inventario:existencias")).content.decode()
