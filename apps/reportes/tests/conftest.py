from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.conteo.servicios import ajustar_bodega, ajustar_pdv
from apps.despacho.models import TrasladoPdv
from apps.despacho.servicios import (
    aceptar_traslado,
    crear_traslado,
    despachar_pedido,
    rechazar_traslado,
)
from apps.embultaje import servicios as embultaje
from apps.embultaje.models import AlistamientoDetalle
from apps.inventario.models import Lote
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import (
    CategoriaProducto,
    Cliente,
    Producto,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)
from apps.puntoventa.servicios import (
    registrar_movimiento_pdv,
    registrar_venta_consumidor,
    registrar_venta_restaurante,
)
from apps.recepcion.servicios import (
    agregar_linea,
    cerrar_documento,
    crear_documento,
    crear_lote_recepcion,
    registrar_pesada,
)
from apps.transformacion.servicios import confirmar_orden, crear_orden


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    """El lote con 30 kg en el cuarto de sostenimiento."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="30", usuario=gerente, ubicacion_destino=bodega
    )
    return lote


@pytest.fixture
def vencido(linea, producto, tunel, gerente):
    """Un lote ya vencido con 5 kg en el túnel."""
    lote = Lote.objects.create(
        codigo="L-000099",
        origen="RECEPCION",
        documento_proveedor_linea=linea,
        producto=producto,
        estado_producto="CONGELADO",
        fecha_vencimiento=date(2020, 1, 1),
    )
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="5", usuario=gerente, ubicacion_destino=tunel
    )
    return lote


@pytest.fixture
def tilapia(db):
    return Producto.objects.create(
        codigo="PES-001",
        nombre="Tilapia",
        unidad_medida="KG",
        categoria=CategoriaProducto.objects.get_or_create(nombre="Pescado")[0],
    )


@pytest.fixture
def otro_punto(db):
    return Ubicacion.objects.create(codigo="PDV-02", nombre="Punto de venta 2", tipo="PUNTO_VENTA")


def _entrada(ubicacion, producto, cantidad, usuario):
    registrar_movimiento_pdv(
        ubicacion=ubicacion,
        producto=producto,
        tipo="ENTRADA_TRASLADO",
        cantidad=cantidad,
        usuario=usuario,
    )


@pytest.fixture
def con_stock(punto_venta, otro_punto, producto, tilapia, gerente):
    """Punto 1: 40 kg de pechuga y 10 de tilapia. Punto 2: 8 kg de pechuga."""
    _entrada(punto_venta, producto, "40", gerente)
    _entrada(punto_venta, tilapia, "10", gerente)
    _entrada(otro_punto, producto, "8", gerente)


@pytest.fixture
def restaurante(db):
    return Cliente.objects.create(
        tipo_documento="NIT",
        numero_documento="900777111",
        razon_social="Restaurante La Ribera",
        autoriza_tratamiento_datos=True,
        fecha_autorizacion="2026-10-01",
    )


@pytest.fixture
def con_ventas(con_stock, punto_venta, otro_punto, producto, tilapia, restaurante, gerente):
    """Tres ventas de hoy.

    Punto 1: factura con 5 kg de pechuga y 2 de tilapia; remisión con 10 kg de pechuga.
    Punto 2: factura con 3 kg de pechuga.
    """
    registrar_venta_consumidor(
        ubicacion=punto_venta,
        numero_factura_siigo="FE-1",
        lineas=[{"producto": producto, "cantidad": "5"}, {"producto": tilapia, "cantidad": "2"}],
        usuario=gerente,
    )
    registrar_venta_restaurante(
        ubicacion=punto_venta,
        cliente=restaurante,
        lineas=[{"producto": producto, "cantidad": "10"}],
        usuario=gerente,
    )
    registrar_venta_consumidor(
        ubicacion=otro_punto,
        numero_factura_siigo="FE-2",
        lineas=[{"producto": producto, "cantidad": "3"}],
        usuario=gerente,
    )


@pytest.fixture
def con_ajustes(en_bodega, bodega, con_stock, punto_venta, producto, gerente):
    """Un ajuste de bodega (resta 2 kg por pérdida) y uno de PDV (suma 1 kg sobrante)."""
    ajustar_bodega(
        lote=en_bodega,
        ubicacion=bodega,
        sentido="SALIDA",
        cantidad="2",
        motivo="PERDIDA",
        observacion="Canastilla rota",
        usuario=gerente,
    )
    ajustar_pdv(
        ubicacion=punto_venta,
        producto=producto,
        sentido="ENTRADA",
        cantidad="1",
        motivo="SOBRANTE",
        observacion="Conteo de cierre",
        usuario=gerente,
    )


@pytest.fixture
def escenario(producto, tilapia, tunel, punto_venta, gerente, jefe_bodega):
    """Una operación completa de hoy, hecha con los servicios reales.

    - Documento F-200 con dos líneas. Pechuga: declarados 52, pesados 50 en la zona de
      transformación (merma de recepción 2). Tilapia: declarados 103, pesados 100 en el túnel
      (merma 3).
    - Se transforman 40 kg de pechuga en 36 de pechuga porcionada (merma 4) y se pierde 1 kg
      de lo porcionado.
    - La tilapia se embulta: 97 kg a la zona de bultos y 3 de merma al cerrar el lote.
    - De la tilapia se trasladan 30 kg aceptados al PDV (otro traslado de 10 se rechaza), se
      despachan 20 a un mayorista y el PDV vende 5.
    """
    hoy = timezone.localdate()
    vence = hoy + timedelta(days=60)
    producto.admite_transformacion = True
    producto.save(update_fields=["admite_transformacion"])
    zona_trf = Ubicacion.objects.create(
        codigo="TRF-01", nombre="Zona de transformación", tipo="ZONA_TRANSFORMACION"
    )
    zona_bultos = Ubicacion.objects.create(
        codigo="BUL-01", nombre="Zona de bultos", tipo="ZONA_BULTOS"
    )
    porciones = Producto.objects.create(
        codigo="POL-002",
        nombre="Pechuga porcionada",
        unidad_medida="KG",
        categoria=producto.categoria,
    )
    canastilla = TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("2.50"))
    proveedor = Proveedor.objects.create(
        tipo_documento="NIT", numero_documento="900999888", razon_social="Pesquera del Sur"
    )

    documento = crear_documento(
        proveedor=proveedor, tipo_documento="FACTURA", numero_documento="F-200", fecha=hoy
    )
    linea_pechuga = agregar_linea(documento=documento, producto=producto, cantidad="52")
    linea_tilapia = agregar_linea(documento=documento, producto=tilapia, cantidad="103")
    lote_pechuga = crear_lote_recepcion(
        linea=linea_pechuga, estado_producto="FRESCO", fecha_vencimiento=vence
    )
    lote_tilapia = crear_lote_recepcion(
        linea=linea_tilapia, estado_producto="CONGELADO", fecha_vencimiento=vence
    )
    for lote, bruto, destino in ((lote_pechuga, "60", zona_trf), (lote_tilapia, "110", tunel)):
        registrar_pesada(
            lote=lote,
            tipo_embalaje=canastilla,
            cantidad_embalajes=4,
            peso_bruto=bruto,
            temperatura="-18",
            ubicacion_destino=destino,
            usuario=jefe_bodega,
        )
    cerrar_documento(documento=documento, usuario=jefe_bodega)

    orden = crear_orden(
        lote=lote_pechuga, ubicacion_origen=zona_trf, cantidad_consumida="40", usuario=jefe_bodega
    )
    confirmar_orden(
        orden=orden,
        derivados=[
            {
                "producto": porciones,
                "cantidad": Decimal("36"),
                "ubicacion_destino": tunel,
                "estado_producto": "CONGELADO",
                "fecha_vencimiento": vence,
            }
        ],
        usuario=jefe_bodega,
        observacion="Corte con piel",
    )
    derivado = Lote.objects.get(lote_origen=lote_pechuga)
    ajustar_bodega(
        lote=derivado,
        ubicacion=tunel,
        sentido="SALIDA",
        cantidad="1",
        motivo="PERDIDA",
        observacion="Bolsa rota",
        usuario=gerente,
    )

    embultaje.registrar_embultaje(
        lote=lote_tilapia,
        ubicacion_origen=tunel,
        ubicacion_destino=zona_bultos,
        usuario=jefe_bodega,
        total_kilos="97",
    )
    embultaje.cerrar_lote(lote=lote_tilapia, usuario=jefe_bodega)

    aceptado = crear_traslado(
        origen=zona_bultos,
        destino=punto_venta,
        nombre_entrega="Luis Gómez",
        lineas=[{"lote": lote_tilapia, "cantidad": "30"}],
        usuario=jefe_bodega,
    )
    aceptar_traslado(
        traslado=aceptado,
        usuario=gerente,
        nombre_coincide=True,
        verificadas={d.pk: d.cantidad for d in aceptado.detalles.all()},
    )
    rechazado = crear_traslado(
        origen=zona_bultos,
        destino=punto_venta,
        nombre_entrega="Luis Gómez",
        lineas=[{"lote": lote_tilapia, "cantidad": "10"}],
        usuario=jefe_bodega,
    )
    rechazar_traslado(traslado=rechazado, usuario=gerente, observacion="Llegó con 9 kg")

    cliente = Cliente.objects.create(
        tipo_documento="NIT", numero_documento="901555444", razon_social="Pescadería El Puerto"
    )
    pedido = embultaje.crear_pedido(cliente=cliente, fecha=hoy, usuario=jefe_bodega)
    linea_pedido = embultaje.agregar_linea(
        pedido=pedido, producto=tilapia, cantidad_solicitada="20", usuario=jefe_bodega
    )
    embultaje.sugerir_fifo(linea=linea_pedido, usuario=jefe_bodega)
    pedido = embultaje.marcar_alistado(pedido=pedido, usuario=jefe_bodega)
    despachar_pedido(
        pedido=pedido,
        usuario=jefe_bodega,
        placa_vehiculo="abc123",
        nombre_conductor="Carlos Pérez",
        tipo_documento="REMISION",
        numero_documento="R-0001",
        lineas=[
            {"alistamiento": d, "cantidad": d.cantidad, "cantidad_bultos_cajas": 2}
            for d in AlistamientoDetalle.objects.filter(pedido_linea__pedido=pedido)
        ],
    )
    registrar_venta_consumidor(
        ubicacion=punto_venta,
        numero_factura_siigo="FE-9",
        lineas=[{"producto": tilapia, "cantidad": "5"}],
        usuario=gerente,
    )
    return {
        "lote_pechuga": lote_pechuga,
        "lote_tilapia": lote_tilapia,
        "derivado": derivado,
        "porciones": porciones,
        "zona_trf": zona_trf,
        "zona_bultos": zona_bultos,
        "linea_pechuga": linea_pechuga,
        "linea_tilapia": linea_tilapia,
        "traslados": TrasladoPdv.objects.order_by("pk"),
    }
