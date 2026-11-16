from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.despacho.servicios import crear_traslado, despachar_pedido
from apps.embultaje.models import AlistamientoDetalle
from apps.embultaje.servicios import agregar_linea, crear_pedido, marcar_alistado, sugerir_fifo
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import Cliente, Ubicacion


@pytest.fixture
def zona_bultos(db):
    return Ubicacion.objects.create(codigo="BUL-01", nombre="Zona de bultos", tipo="ZONA_BULTOS")


@pytest.fixture
def cliente(db):
    return Cliente.objects.create(
        tipo_documento="NIT", numero_documento="901555444", razon_social="Pescadería El Puerto"
    )


@pytest.fixture
def en_bultos(lote, zona_bultos, gerente):
    """El lote con 100 kg embultados, vigente para que FIFO lo ofrezca."""
    lote.fecha_vencimiento = timezone.localdate() + timedelta(days=60)
    lote.save(update_fields=["fecha_vencimiento"])
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="100", usuario=gerente, ubicacion_destino=zona_bultos
    )
    return lote


@pytest.fixture
def alistar(en_bultos, cliente, producto, jefe_bodega):
    """Crea un pedido del producto por `kg`, lo cubre por FIFO y lo deja ALISTADO."""

    def crear(kg="60"):
        pedido = crear_pedido(cliente=cliente, fecha=timezone.localdate(), usuario=jefe_bodega)
        linea = agregar_linea(
            pedido=pedido, producto=producto, cantidad_solicitada=kg, usuario=jefe_bodega
        )
        sugerir_fifo(linea=linea, usuario=jefe_bodega)
        return marcar_alistado(pedido=pedido, usuario=jefe_bodega)

    return crear


@pytest.fixture
def alistado(alistar):
    return alistar()


def lineas_de(pedido, **cambios):
    """Las líneas del despacho tal como las arma la pantalla: lo planeado, con cambios."""
    return [
        {"alistamiento": d, "cantidad": d.cantidad, "cantidad_bultos_cajas": 3, **cambios}
        for d in AlistamientoDetalle.objects.filter(pedido_linea__pedido=pedido).order_by("pk")
    ]


@pytest.fixture
def despachar(jefe_bodega):
    """Despacha un pedido con datos válidos por defecto; acepta cambios."""

    def hacer(pedido, **cambios):
        datos = {
            "pedido": pedido,
            "usuario": jefe_bodega,
            "placa_vehiculo": "abc123",
            "nombre_conductor": "Carlos Pérez",
            "tipo_documento": "REMISION",
            "numero_documento": "R-0001",
            "lineas": lineas_de(pedido),
            **cambios,
        }
        return despachar_pedido(**datos)

    return hacer


@pytest.fixture
def enviar(en_bultos, zona_bultos, punto_venta, jefe_bodega):
    """Envía `kg` del lote embultado al punto de venta; acepta cambios."""

    def hacer(kg="30", **cambios):
        datos = {
            "origen": zona_bultos,
            "destino": punto_venta,
            "nombre_entrega": "Luis Gómez",
            "lineas": [{"lote": en_bultos, "cantidad": kg}],
            "usuario": jefe_bodega,
            **cambios,
        }
        return crear_traslado(**datos)

    return hacer


def pesos_de(traslado, cambios=None):
    """Lo que pesa el PDV al recibir: lo declarado, salvo los lotes indicados por código."""
    cambios = cambios or {}
    return {
        d.pk: Decimal(cambios.get(d.lote.codigo, d.cantidad))
        for d in traslado.detalles.select_related("lote")
    }
