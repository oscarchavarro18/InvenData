"""Informe general de inventario por periodo y alcance (RF-63, RF-64, RF-65)."""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from apps.reportes import consultas
from apps.reportes.consultas.clasificacion import acumular, columnas_vacias, neto


def _hoy():
    return timezone.localdate()


def _seccion(reporte, titulo):
    return next(s for s in reporte.secciones if s.titulo == titulo)


def _por_producto(reporte):
    return {f["producto"]: f for f in _seccion(reporte, "Resumen por producto").filas}


def _informe(usuario, alcance="", **filtros):
    filtros.setdefault("desde", _hoy())
    filtros.setdefault("hasta", _hoy())
    return consultas.informe_general(
        alcance=consultas.resolver_alcance(usuario, alcance), **filtros
    )


def test_traslado_interno_no_cambia_el_total():
    fila = columnas_vacias()
    acumular(fila, "TRASLADO", Decimal("5"), entra=True, sale=True)
    acumular(fila, "ENTRADA", Decimal("10"), entra=True, sale=False)
    acumular(fila, "AJUSTE", Decimal("2"), entra=False, sale=True)
    assert (fila["t_entran"], fila["t_salen"], fila["ajustes"]) == (5, 5, -2)
    assert neto(fila) == Decimal("8")


def test_toda_la_operacion_cuadra(gerente, escenario):
    """RF-64: inicial, movimientos clasificados y final; cuadra con la existencia de hoy."""
    reporte = _informe(gerente)
    tilapia = _por_producto(reporte)["Tilapia"]
    assert tilapia["entradas"] == Decimal("100")
    assert tilapia["salidas"] == Decimal("25")  # 20 despachados + 5 vendidos
    # Embultaje (97) y traslado a PDV (30) salen de un lado y entran al otro.
    assert (tilapia["t_entran"], tilapia["t_salen"]) == (Decimal("127"), Decimal("127"))
    assert tilapia["mermas"] == Decimal("3")
    assert tilapia["final"] == tilapia["registrada"] == Decimal("72")
    assert tilapia["cuadre"] == "Cuadra"
    porcionada = _por_producto(reporte)["Pechuga porcionada"]
    assert (porcionada["mermas"], porcionada["final"]) == (Decimal("1"), Decimal("35"))
    resumen = {e: v for e, v, _ in reporte.resumen}
    assert resumen["Verificación de cuadre"] == "Cuadra en 3 de 3 productos"
    assert resumen["Inventario final"] == Decimal("117")  # 72 + 35 + 10


def test_alcance_toda_la_bodega(gerente, escenario):
    """RF-65: sin el PDV, el traslado al punto es una salida de la bodega."""
    tilapia = _por_producto(_informe(gerente, "BODEGA"))["Tilapia"]
    assert (tilapia["t_entran"], tilapia["t_salen"]) == (Decimal("97"), Decimal("127"))
    assert tilapia["salidas"] == Decimal("20")
    assert tilapia["final"] == Decimal("47")
    assert tilapia["cuadre"] == "Cuadra"


def test_alcance_una_zona(gerente, escenario):
    zona = escenario["zona_bultos"]
    tilapia = _por_producto(_informe(gerente, f"U{zona.pk}"))["Tilapia"]
    assert tilapia["t_entran"] == Decimal("97")
    assert tilapia["final"] == Decimal("47")


def test_admin_pdv_solo_su_punto(admin_pdv, escenario):
    """RN-07: aunque pida la bodega, el informe sale con su punto."""
    zona = escenario["zona_bultos"]
    reporte = _informe(admin_pdv, f"U{zona.pk}")
    assert list(_por_producto(reporte)) == ["Tilapia"]
    tilapia = _por_producto(reporte)["Tilapia"]
    assert (tilapia["t_entran"], tilapia["salidas"], tilapia["final"]) == (
        Decimal("30"),
        Decimal("5"),
        Decimal("25"),
    )
    assert ("Alcance", "Punto de venta: Punto de venta 1") in reporte.filtros


def test_filtro_por_lote_solo_cuenta_bodega(gerente, escenario):
    """RF-63: por lote; el PDV no maneja lote (SN-09)."""
    reporte = _informe(gerente, lote=escenario["lote_tilapia"])
    assert list(_por_producto(reporte)) == ["Tilapia"]
    assert _por_producto(reporte)["Tilapia"]["final"] == Decimal("47")
    assert "no maneja lote" in reporte.nota


def test_inventario_inicial_viene_del_libro(gerente, escenario):
    """El final de hoy es el inicial de mañana."""
    manana = _hoy() + timedelta(days=1)
    tilapia = _por_producto(_informe(gerente, desde=manana, hasta=manana))["Tilapia"]
    assert tilapia["inicial"] == tilapia["final"] == Decimal("72")


def test_corte_anterior_a_hoy_no_verifica_cuadre(gerente, escenario):
    ayer = _hoy() - timedelta(days=1)
    reporte = _informe(gerente, desde=ayer, hasta=ayer)
    assert _seccion(reporte, "Resumen por producto").filas == []
    resumen = {e: v for e, v, _ in reporte.resumen}
    assert resumen["Verificación de cuadre"].startswith("No aplica")


def test_detalle_y_totales_por_tipo(gerente, escenario):
    reporte = _informe(gerente, "BODEGA")
    tipos = {f["tipo"]: f for f in _seccion(reporte, "Totales por tipo de movimiento").filas}
    assert tipos["Embultaje (dentro del alcance)"]["kg"] == Decimal("97")
    assert tipos["Merma de embultaje"]["clase"] == "Merma"
    detalle = _seccion(reporte, "Detalle de movimientos del periodo").filas
    embultaje = next(f for f in detalle if f["tipo"] == "Embultaje")
    assert embultaje["efecto"] == Decimal("0")


def test_vista_alcances_por_perfil(client, jefe_bodega, admin_pdv, gerente, escenario):
    client.force_login(jefe_bodega)
    contenido = client.get(reverse("reportes:informe")).content.decode()
    assert "Toda la bodega" in contenido
    assert "Punto de venta: " not in contenido

    client.force_login(admin_pdv)
    contenido = client.get(reverse("reportes:informe")).content.decode()
    assert "Toda la bodega" not in contenido
    assert 'name="lote"' not in contenido

    client.force_login(gerente)
    csv = client.get(reverse("reportes:informe"), {"formato": "csv"}).content.decode("utf-8")
    assert "Resumen por producto" in csv
    assert "Detalle de movimientos del periodo" in csv


def test_lote_inexistente_avisa(client, gerente, escenario):
    client.force_login(gerente)
    respuesta = client.get(reverse("reportes:informe"), {"lote": "L-999999"})
    assert "No existe un lote con el código L-999999." in respuesta.content.decode()
