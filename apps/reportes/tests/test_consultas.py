"""Contenido de los reportes de M9 (RF-56 a RF-60)."""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.conteo.servicios import reversar_pdv
from apps.maestros.models import Ubicacion
from apps.puntoventa.models import MovimientoPuntoVenta
from apps.reportes import consultas


def _resumen(reporte):
    return {etiqueta: valor for etiqueta, valor, _ in reporte.resumen}


def _hoy():
    return timezone.localdate()


def test_existencias_bodega_por_ubicacion_y_lote(en_bodega, vencido):
    """RF-56: cada lote en su ubicación, con días para vencer y total general."""
    reporte = consultas.existencias_bodega()
    assert [f["lote"] for f in reporte.filas] == ["L-000001", "L-000099"]
    assert reporte.totales["kg"] == Decimal("35")
    resumen = _resumen(reporte)
    assert resumen["Lotes"] == 2
    assert resumen["Lotes vencidos"] == 1
    assert resumen["Mayor existencia"].startswith("Pechuga")


def test_existencias_bodega_filtra_por_ubicacion(en_bodega, vencido, tunel):
    reporte = consultas.existencias_bodega(ubicacion=tunel)
    assert [f["lote"] for f in reporte.filas] == ["L-000099"]
    assert ("Ubicación", tunel.nombre) in reporte.filtros


def test_existencias_pdv_con_participacion(con_stock, punto_venta):
    """RF-57: kg por producto y participación sobre el total del alcance."""
    reporte = consultas.existencias_pdv(puntos=Ubicacion.objects.filter(tipo="PUNTO_VENTA"))
    assert reporte.totales["kg"] == Decimal("58")
    filas = {(f["ubicacion"], f["codigo"]): f for f in reporte.filas}
    pechuga_1 = filas[(punto_venta.nombre, "POL-001")]
    assert round(pechuga_1["participacion"], 1) == Decimal("69.0")


def test_por_vencer_separa_vencidos(en_bodega, vencido):
    """RF-58: el vencido aparece primero; el lote de diciembre no entra con 7 días."""
    reporte = consultas.por_vencer(dias=7)
    assert [f["situacion"] for f in reporte.filas] == ["Vencido"]
    assert reporte.filas[0]["ubicaciones"] == "Túnel de congelación 1"
    assert _resumen(reporte)["Kg vencidos"] == Decimal("5")


def test_por_vencer_con_horizonte_amplio(en_bodega, vencido):
    dias = (en_bodega.fecha_vencimiento - _hoy()).days + 1
    reporte = consultas.por_vencer(dias=dias)
    assert [f["situacion"] for f in reporte.filas] == ["Vencido", "Por vencer"]


def test_ventas_por_punto_producto_y_canal(con_ventas):
    """RF-59: detalle por punto, producto y canal, con totales y cifras clave."""
    puntos = Ubicacion.objects.filter(tipo="PUNTO_VENTA")
    reporte = consultas.ventas(puntos=puntos, desde=_hoy(), hasta=_hoy())
    assert reporte.totales["kg"] == Decimal("20")
    assert reporte.totales["ventas"] == 3
    primera = reporte.filas[0]  # la de más kg
    assert (primera["producto"], primera["canal"], primera["kg"]) == (
        "Pechuga",
        "Restaurante",
        Decimal("10"),
    )
    resumen = _resumen(reporte)
    assert resumen["Kg a consumidor final"] == Decimal("10")
    assert resumen["Kg a restaurantes"] == Decimal("10")
    assert resumen["Producto más vendido"] == "Pechuga"


def test_ventas_agrupadas_por_producto_juntan_canales(con_ventas):
    puntos = Ubicacion.objects.filter(tipo="PUNTO_VENTA")
    reporte = consultas.ventas(puntos=puntos, desde=_hoy(), hasta=_hoy(), agrupar="producto")
    filas = {f["producto"]: f for f in reporte.filas}
    assert filas["Pechuga"]["kg"] == Decimal("18")
    assert filas["Pechuga"]["ventas"] == 3
    assert filas["Tilapia"]["kg"] == Decimal("2")
    assert [c.clave for c in reporte.columnas][0] == "producto"


def test_ventas_por_canal_y_filtro_de_canal(con_ventas):
    puntos = Ubicacion.objects.filter(tipo="PUNTO_VENTA")
    por_canal = consultas.ventas(puntos=puntos, desde=_hoy(), hasta=_hoy(), agrupar="canal")
    assert {f["canal"]: f["ventas"] for f in por_canal.filas} == {
        "Consumidor final": 2,
        "Restaurante": 1,
    }
    solo = consultas.ventas(puntos=puntos, desde=_hoy(), hasta=_hoy(), canal="RESTAURANTE")
    assert solo.totales["kg"] == Decimal("10")


def test_ventas_respetan_el_alcance_y_el_periodo(con_ventas, otro_punto):
    """RN-07: solo cuentan los puntos que se pasan; fuera del periodo no hay ventas."""
    reporte = consultas.ventas(
        puntos=Ubicacion.objects.filter(pk=otro_punto.pk), desde=_hoy(), hasta=_hoy()
    )
    assert reporte.totales["kg"] == Decimal("3")
    ayer = _hoy() - timedelta(days=1)
    vacio = consultas.ventas(
        puntos=Ubicacion.objects.filter(tipo="PUNTO_VENTA"), desde=ayer, hasta=ayer
    )
    assert vacio.filas == []
    assert _resumen(vacio)["Kg promedio por venta"] == Decimal("0")


def test_correcciones_de_bodega_y_pdv(con_ajustes):
    """RF-60: ajustes con sentido, motivo, quién y justificación."""
    puntos = Ubicacion.objects.filter(tipo="PUNTO_VENTA")
    reporte = consultas.correcciones(ver_bodega=True, puntos=puntos, desde=_hoy(), hasta=_hoy())
    assert {(f["ambito"], f["kg"], f["motivo"]) for f in reporte.filas} == {
        ("Bodega", Decimal("-2"), "Pérdida"),
        ("Punto de venta", Decimal("1"), "Sobrante"),
    }
    resumen = _resumen(reporte)
    assert resumen["Kg sumados"] == Decimal("1")
    assert resumen["Kg restados"] == Decimal("2")
    assert resumen["Efecto neto"] == Decimal("-1")
    assert all(f["usuario"] == "Gerente de prueba" for f in reporte.filas)


def test_correcciones_sin_bodega_ni_otros_puntos(con_ajustes, punto_venta):
    """RN-06: sin bodega solo aparecen los ajustes del punto que se ve."""
    reporte = consultas.correcciones(
        ver_bodega=False,
        puntos=Ubicacion.objects.filter(pk=punto_venta.pk),
        desde=_hoy(),
        hasta=_hoy(),
    )
    assert [f["ambito"] for f in reporte.filas] == ["Punto de venta"]
    assert ("Ámbito", "Punto de venta") in reporte.filtros


def test_correcciones_incluyen_reversos(con_ventas, punto_venta, gerente):
    venta = MovimientoPuntoVenta.objects.filter(tipo="VENTA", ubicacion=punto_venta).first()
    reversar_pdv(movimiento=venta, usuario=gerente, observacion="Factura anulada en Siigo")
    reporte = consultas.correcciones(
        ver_bodega=False,
        puntos=Ubicacion.objects.filter(pk=punto_venta.pk),
        desde=_hoy(),
        hasta=_hoy(),
    )
    assert [f["clase"] for f in reporte.filas] == ["Reverso"]
    assert reporte.filas[0]["motivo"] == "Error de conteo"
    assert _resumen(reporte)["Reversos"] == 1
