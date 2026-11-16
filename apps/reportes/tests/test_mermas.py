"""Reporte consolidado de mermas (RF-55)."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.conteo.servicios import reversar_bodega
from apps.inventario.models import Movimiento
from apps.reportes import consultas


def _hoy():
    return timezone.localdate()


def _seccion(reporte, titulo):
    return next(s for s in reporte.secciones if s.titulo == titulo)


def test_merma_por_etapa(escenario):
    """Recepción 5, transformación 4, embultaje 3 y una pérdida de 1 kg."""
    reporte = consultas.mermas(desde=_hoy(), hasta=_hoy())
    etapas = {f["etapa"]: f for f in _seccion(reporte, "Merma por etapa en el periodo").filas}
    assert etapas["Recepción"]["base"] == Decimal("155")
    assert etapas["Recepción"]["merma"] == Decimal("5")
    assert etapas["Transformación"]["merma"] == Decimal("4")
    assert round(etapas["Transformación"]["porcentaje"], 1) == Decimal("10.0")
    assert etapas["Embultaje"]["base"] == Decimal("100")
    assert etapas["Embultaje"]["merma"] == Decimal("3")
    assert etapas["Pérdidas y vencimientos"]["merma"] == Decimal("1")
    resumen = {e: v for e, v, _ in reporte.resumen}
    assert resumen["Merma del periodo"] == Decimal("13")
    assert resumen["Etapa con más merma"] == "Recepción"


def test_merma_acumulada_por_linea_suma_derivados(escenario):
    """RF-55: de lo declarado a lo aprovechado, con los lotes derivados de la línea."""
    reporte = consultas.mermas(desde=_hoy(), hasta=_hoy())
    lineas = {
        f["producto"]: f for f in _seccion(reporte, "Merma acumulada por línea de recepción").filas
    }
    pechuga = lineas["Pechuga"]
    assert pechuga["lotes"] == 2  # el de recepción y su derivado
    assert (pechuga["recepcion"], pechuga["transformacion"], pechuga["perdidas"]) == (
        Decimal("2"),
        Decimal("4"),
        Decimal("1"),
    )
    assert pechuga["total"] == Decimal("7")
    assert pechuga["aprovechado"] == Decimal("45")
    tilapia = lineas["Tilapia"]
    assert (tilapia["recepcion"], tilapia["embultaje"], tilapia["total"]) == (
        Decimal("3"),
        Decimal("3"),
        Decimal("6"),
    )
    assert tilapia["aprovechado"] == Decimal("97")


def test_una_perdida_reversada_no_cuenta(escenario, gerente):
    """RF-09: el reverso deja sin efecto la pérdida, también en las mermas."""
    perdida = Movimiento.objects.get(tipo="AJUSTE_CONTEO", motivo_ajuste="PERDIDA")
    reversar_bodega(movimiento=perdida, usuario=gerente, observacion="La bolsa apareció")
    reporte = consultas.mermas(desde=_hoy(), hasta=_hoy())
    lineas = {
        f["producto"]: f for f in _seccion(reporte, "Merma acumulada por línea de recepción").filas
    }
    assert lineas["Pechuga"]["perdidas"] == Decimal("0")


def test_periodo_sin_movimientos(escenario):
    ayer = _hoy() - timedelta(days=1)
    reporte = consultas.mermas(desde=ayer, hasta=ayer)
    assert _seccion(reporte, "Merma acumulada por línea de recepción").filas == []
    assert {e: v for e, v, _ in reporte.resumen}["Etapa con más merma"] == "Ninguna"


def test_filtro_por_producto(escenario, tilapia):
    reporte = consultas.mermas(desde=_hoy(), hasta=_hoy(), producto=tilapia)
    etapas = {f["etapa"]: f for f in _seccion(reporte, "Merma por etapa en el periodo").filas}
    assert etapas["Recepción"]["merma"] == Decimal("3")
    assert etapas["Transformación"]["merma"] == Decimal("0")


def test_vista_y_permisos(client, jefe_bodega, admin_pdv, escenario):
    client.force_login(jefe_bodega)
    respuesta = client.get(reverse("reportes:mermas"), {"formato": "csv"})
    assert "Merma acumulada por línea de recepción" in respuesta.content.decode("utf-8")
    client.force_login(admin_pdv)
    assert client.get(reverse("reportes:mermas")).status_code == 403
