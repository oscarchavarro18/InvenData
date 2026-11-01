"""Indicadores de gestión (RF-61)."""

from django.urls import reverse
from django.utils import timezone

from apps.conteo.servicios import ajustar_bodega
from apps.reportes import consultas
from apps.reportes.consultas.comun import periodo_por_defecto


def _indicadores(**alcance):
    desde, hasta = periodo_por_defecto()
    return consultas.indicadores(desde=desde, hasta=hasta, **alcance)


def _valores(reporte):
    return {f["indicador"]: f["valor"] for f in reporte.filas}


def test_indicadores_de_bodega(escenario, punto_venta):
    """RF-61: merma total, rendimiento, traslados rechazados y FIFO."""
    valores = _valores(_indicadores(ver_bodega=True, puntos=[punto_venta]))
    assert valores["Merma total del periodo"] == "13,00"
    assert valores["Rendimiento de transformación"] == "90,0 %"
    assert valores["Traslados a punto de venta rechazados"] == "50,0 %"
    assert valores["Cumplimiento de FIFO en el alistamiento"] == "100,0 %"
    assert valores["Kg despachados a mayoristas"] == "20,00"
    assert valores["Kg trasladados a puntos de venta"] == "30,00"


def test_indicadores_de_punto_de_venta(escenario, punto_venta):
    valores = _valores(_indicadores(ver_bodega=False, puntos=[punto_venta]))
    assert valores["Kg vendidos"] == "5,00"
    # 25 kg en vitrina a 5 kg cada 30 días: 150 días de cobertura.
    assert valores["Cobertura del inventario"] == "150,0"
    assert "Merma total del periodo" not in valores


def test_tiempo_entre_recepcion_y_salida(en_bodega, bodega, gerente):
    """Un lote que se agota hoy tarda cero días entre su ingreso y su salida."""
    ajustar_bodega(
        lote=en_bodega,
        ubicacion=bodega,
        sentido="SALIDA",
        cantidad="30",
        motivo="VENCIMIENTO",
        observacion="Se dio de baja",
        usuario=gerente,
    )
    fila = next(
        f
        for f in _indicadores(ver_bodega=True, puntos=[]).filas
        if f["indicador"] == "Tiempo entre recepción y salida de un lote"
    )
    assert fila["valor"] == "0,0"
    assert fila["detalle"].startswith("Promedio de 1 lotes agotados")


def test_sin_datos_no_rompe(db):
    valores = _valores(_indicadores(ver_bodega=True, puntos=[]))
    assert valores["Rendimiento de transformación"] == "Sin datos"
    assert valores["Tiempo entre recepción y salida de un lote"] == "Sin datos"


def test_vista_segun_perfil(client, admin_pdv, jefe_bodega, escenario):
    client.force_login(admin_pdv)
    contenido = client.get(reverse("reportes:indicadores")).content.decode()
    assert "Kg vendidos" in contenido
    assert "Merma total del periodo" not in contenido

    client.force_login(jefe_bodega)
    contenido = client.get(reverse("reportes:indicadores")).content.decode()
    assert "Merma total del periodo" in contenido
    assert "Kg vendidos" not in contenido


def test_descarga_pdf(client, gerente, escenario):
    client.force_login(gerente)
    respuesta = client.get(reverse("reportes:indicadores"), {"formato": "pdf"})
    assert respuesta.content.startswith(b"%PDF")
    assert timezone.localdate().strftime("%Y%m%d") in respuesta["Content-Disposition"]
