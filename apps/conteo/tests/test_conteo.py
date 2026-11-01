"""Conteo físico: registro, alcance y comparación informal (RF-50, RF-51, RF-52, RN-36)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.conteo.consultas import comparacion
from apps.conteo.models import ConteoFisico, ConteoFisicoDetalle
from apps.conteo.servicios import ConteoInvalido, registrar_conteo
from apps.inventario.models import Movimiento
from apps.puntoventa.models import MovimientoPuntoVenta


def contar(ubicacion, usuario, lineas, fecha=None):
    return registrar_conteo(
        ubicacion=ubicacion,
        fecha=fecha or timezone.localdate(),
        lineas=lineas,
        usuario=usuario,
    )


def bultos(producto, cantidad):
    return {"producto": producto, "cantidad_bultos": cantidad}


# --- Servicio ----------------------------------------------------------------


def test_el_conteo_queda_registrado_y_no_mueve_inventario(bodega, jefe_bodega, en_bodega):
    """RF-50, RF-51 y RN-36."""
    antes = Movimiento.objects.count()
    conteo = contar(bodega, jefe_bodega, [bultos(en_bodega.producto, 6)])
    assert conteo.detalles.get().cantidad_bultos == 6
    assert Movimiento.objects.count() == antes
    assert Auditoria.objects.filter(entidad="conteo_fisico", registro_id=conteo.pk).exists()


def test_el_pdv_cuenta_su_punto(punto_venta, admin_pdv, en_punto):
    antes = MovimientoPuntoVenta.objects.count()
    contar(punto_venta, admin_pdv, [bultos(en_punto, 4)])
    assert MovimientoPuntoVenta.objects.count() == antes


@pytest.mark.parametrize(
    ("perfil", "donde"),
    [
        ("admin_pdv", "bodega"),  # RN-06: el PDV no toca la bodega
        ("jefe_bodega", "punto_venta"),  # bodega no cuenta los PDV
        ("consulta", "bodega"),  # solo lectura
    ],
)
def test_cada_quien_cuenta_lo_que_opera(request, perfil, donde, producto):
    with pytest.raises(PermissionDenied):
        contar(
            request.getfixturevalue(donde),
            request.getfixturevalue(perfil),
            [bultos(producto, 1)],
        )


@pytest.mark.parametrize(
    ("lineas", "fecha", "mensaje"),
    [
        ([], None, "al menos un producto"),
        ("repetida", None, "una sola vez"),
        ("negativa", None, "entero no negativo"),
        ("una", "futura", "no puede ser futura"),
    ],
)
def test_el_conteo_debe_ser_valido(bodega, jefe_bodega, producto, lineas, fecha, mensaje):
    if lineas == "repetida":
        lineas = [bultos(producto, 1), bultos(producto, 2)]
    elif lineas == "negativa":
        lineas = [bultos(producto, -1)]
    elif lineas == "una":
        lineas = [bultos(producto, 1)]
    if fecha == "futura":
        fecha = timezone.localdate() + timedelta(days=1)
    with pytest.raises(ConteoInvalido, match=mensaje):
        contar(bodega, jefe_bodega, lineas, fecha)
    assert not ConteoFisico.objects.exists()


def test_la_base_no_repite_producto_en_un_conteo(bodega, jefe_bodega, producto):
    conteo = contar(bodega, jefe_bodega, [bultos(producto, 1)])
    with pytest.raises(IntegrityError), transaction.atomic():
        ConteoFisicoDetalle.objects.create(
            conteo_fisico=conteo, producto=producto, cantidad_bultos=2
        )


def test_la_comparacion_pone_al_lado_lo_que_dice_el_sistema(
    bodega, punto_venta, jefe_bodega, admin_pdv, en_bodega, en_punto
):
    """RF-52: informal, sin diferencia calculada; bultos frente a kg."""
    (fila,) = comparacion(contar(bodega, jefe_bodega, [bultos(en_bodega.producto, 6)]))
    assert (fila["detalle"].cantidad_bultos, fila["kg_sistema"]) == (6, Decimal("30"))
    (fila,) = comparacion(contar(punto_venta, admin_pdv, [bultos(en_punto, 4)]))
    assert fila["kg_sistema"] == Decimal("20")


# --- Pantallas ---------------------------------------------------------------


def _datos(ubicacion, producto, cantidad="5"):
    return {
        "ubicacion": ubicacion.pk,
        "fecha": timezone.localdate().isoformat(),
        "form-TOTAL_FORMS": "8",
        "form-INITIAL_FORMS": "0",
        "form-MIN_NUM_FORMS": "0",
        "form-MAX_NUM_FORMS": "1000",
        "form-0-producto": producto.pk,
        "form-0-cantidad_bultos": cantidad,
    }


def test_registrar_el_conteo_desde_la_pantalla(client, jefe_bodega, bodega, punto_venta, producto):
    client.force_login(jefe_bodega)
    formulario = client.get(reverse("conteo:conteo_nuevo"))
    assert list(formulario.context["form"].fields["ubicacion"].queryset) == [bodega]

    respuesta = client.post(reverse("conteo:conteo_nuevo"), _datos(bodega, producto), follow=True)

    conteo = ConteoFisico.objects.get()
    assert respuesta.redirect_chain[-1][0] == reverse("conteo:conteo_detalle", args=[conteo.pk])
    assert "No modifica la existencia" in respuesta.content.decode()


def test_cada_quien_ve_los_conteos_de_su_alcance(
    client, jefe_bodega, admin_pdv, consulta, bodega, punto_venta, producto
):
    de_bodega = contar(bodega, jefe_bodega, [bultos(producto, 1)])
    del_punto = contar(punto_venta, admin_pdv, [bultos(producto, 1)])
    lista = reverse("conteo:conteo_lista")

    client.force_login(jefe_bodega)
    assert list(client.get(lista).context["pagina"]) == [de_bodega]
    client.force_login(admin_pdv)
    assert list(client.get(lista).context["pagina"]) == [del_punto]
    assert client.get(reverse("conteo:conteo_detalle", args=[de_bodega.pk])).status_code == 403
    client.force_login(consulta)
    assert client.get(lista).context["pagina"].paginator.count == 2
    assert client.get(reverse("conteo:conteo_nuevo")).status_code == 403


def test_el_menu_ofrece_el_conteo(client, admin_pdv):
    client.force_login(admin_pdv)
    assert reverse("conteo:conteo_lista") in client.get(reverse("inicio")).content.decode()
