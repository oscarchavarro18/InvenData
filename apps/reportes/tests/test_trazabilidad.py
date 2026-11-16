"""Trazabilidad de punta a punta de un lote (RF-54, RF-28)."""

from decimal import Decimal

from django.urls import reverse

from apps.reportes import consultas


def _seccion(reporte, titulo):
    return next(s for s in reporte.secciones if s.titulo == titulo)


def _resumen(reporte):
    return {etiqueta: valor for etiqueta, valor, _ in reporte.resumen}


def _datos(reporte):
    return {f["dato"]: f["valor"] for f in _seccion(reporte, "Identificación y origen").filas}


def test_lote_recibido_embultado_trasladado_y_despachado(escenario):
    """RF-54: documento, tandas, embultaje y en qué despacho o traslado salió."""
    reporte = consultas.trazabilidad(escenario["lote_tilapia"])
    datos = _datos(reporte)
    assert datos["Proveedor"] == "Pesquera del Sur"
    assert "F-200" in datos["Documento del proveedor"]
    assert datos["Merma de embultaje"] == "3,00 kg"

    tanda = _seccion(reporte, "Tandas de pesaje").filas[0]
    assert (tanda["bruto"], tanda["tara"], tanda["neto"]) == (
        Decimal("110"),
        Decimal("10"),
        Decimal("100"),
    )
    assert _seccion(reporte, "Embultaje").filas[0]["kg"] == Decimal("97")
    despacho = _seccion(reporte, "Despachos a mayoristas").filas[0]
    assert (despacho["cliente"], despacho["kg"]) == ("Pescadería El Puerto", Decimal("20"))
    estados = [t["estado"] for t in _seccion(reporte, "Traslados a puntos de venta").filas]
    assert estados == ["Aceptado", "Rechazado"]


def test_balance_del_lote_cuadra(escenario):
    """El rechazado no sale de bodega: queda lo que dice la existencia registrada."""
    reporte = consultas.trazabilidad(escenario["lote_tilapia"])
    balance = {f["concepto"]: f["kg"] for f in _seccion(reporte, "Balance del lote").filas}
    assert balance == {
        "Ingresó por recepción": Decimal("100"),
        "Despachado a mayoristas": Decimal("-20"),
        "Trasladado a puntos de venta": Decimal("-30"),
        "Merma de embultaje": Decimal("-3"),
    }
    assert "Cuadra" in _seccion(reporte, "Balance del lote").nota
    resumen = _resumen(reporte)
    assert resumen["Queda en bodega"] == Decimal("47")
    assert resumen["Perdido"] == Decimal("3")
    assert resumen["Situación"] == "Con existencia"


def test_lote_transformado_lleva_a_sus_derivados(escenario):
    """RF-28: el origen muestra la orden y los lotes derivados."""
    reporte = consultas.trazabilidad(escenario["lote_pechuga"])
    orden = _seccion(reporte, "Transformaciones en que se consumió").filas[0]
    assert orden["merma"] == Decimal("4")
    assert escenario["derivado"].codigo in orden["derivados"]
    derivados = _seccion(reporte, "Lotes derivados").filas
    assert [d["lote"] for d in derivados] == [escenario["derivado"].codigo]
    assert _resumen(reporte)["Consumido en transformación"] == Decimal("40")


def test_derivado_apunta_a_su_origen(escenario):
    reporte = consultas.trazabilidad(escenario["derivado"])
    datos = _datos(reporte)
    assert datos["Lote de origen"] == escenario["lote_pechuga"].codigo
    assert datos["Orden de transformación"].startswith("OT-")
    balance = {f["concepto"]: f["kg"] for f in _seccion(reporte, "Balance del lote").filas}
    assert balance == {
        "Ingresó por transformación": Decimal("36"),
        "Pérdidas y vencimientos": Decimal("-1"),
    }


def test_pantalla_busca_por_codigo_sin_importar_mayusculas(client, jefe_bodega, escenario):
    client.force_login(jefe_bodega)
    codigo = escenario["lote_tilapia"].codigo.lower()
    respuesta = client.get(reverse("reportes:trazabilidad"), {"lote": codigo})
    contenido = respuesta.content.decode()
    assert respuesta.status_code == 200
    assert "Tandas de pesaje" in contenido
    assert "Pescadería El Puerto" in contenido


def test_sin_codigo_solo_muestra_el_buscador(client, gerente):
    client.force_login(gerente)
    contenido = client.get(reverse("reportes:trazabilidad")).content.decode()
    assert 'name="lote"' in contenido
    assert "Descargar CSV" not in contenido


def test_codigo_inexistente_avisa(client, gerente, db):
    client.force_login(gerente)
    contenido = client.get(reverse("reportes:trazabilidad"), {"lote": "L-999999"}).content
    assert "No existe un lote con el código L-999999." in contenido.decode()


def test_descargas_con_todas_las_secciones(client, gerente, escenario):
    client.force_login(gerente)
    url = reverse("reportes:trazabilidad")
    codigo = escenario["lote_tilapia"].codigo
    csv = client.get(url, {"lote": codigo, "formato": "csv"}).content.decode("utf-8")
    for titulo in ("Tandas de pesaje", "Despachos a mayoristas", "Balance del lote"):
        assert titulo in csv
    pdf = client.get(url, {"lote": codigo, "formato": "pdf"})
    assert pdf.content.startswith(b"%PDF")


def test_admin_pdv_no_traza_lotes(client, admin_pdv, escenario):
    """RN-06: los lotes son de bodega."""
    client.force_login(admin_pdv)
    url = reverse("reportes:trazabilidad")
    assert client.get(url, {"lote": escenario["lote_tilapia"].codigo}).status_code == 403


def test_ficha_del_lote_enlaza_la_trazabilidad(client, gerente, escenario):
    client.force_login(gerente)
    lote = escenario["lote_tilapia"]
    contenido = client.get(reverse("inventario:lote_detalle", args=[lote.pk])).content.decode()
    assert f"{reverse('reportes:trazabilidad')}?lote={lote.codigo}" in contenido
