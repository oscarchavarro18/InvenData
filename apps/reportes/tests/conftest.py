from datetime import date

import pytest

from apps.conteo.servicios import ajustar_bodega, ajustar_pdv
from apps.inventario.models import Lote
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import CategoriaProducto, Cliente, Producto, Ubicacion
from apps.puntoventa.servicios import (
    registrar_movimiento_pdv,
    registrar_venta_consumidor,
    registrar_venta_restaurante,
)


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
