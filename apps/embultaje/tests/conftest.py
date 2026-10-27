from datetime import timedelta

import pytest
from django.utils import timezone

from apps.embultaje.servicios import agregar_linea, crear_pedido, registrar_embultaje
from apps.inventario.models import Lote
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import Cliente, Ubicacion


@pytest.fixture
def zona_bultos(db):
    return Ubicacion.objects.create(codigo="BUL-01", nombre="Zona de bultos", tipo="ZONA_BULTOS")


@pytest.fixture
def en_bodega(lote, bodega, gerente):
    """El lote con 100 kg en el cuarto de sostenimiento, como tras cerrar su recepción."""
    registrar_movimiento(
        lote=lote, tipo="RECEPCION", cantidad="100", usuario=gerente, ubicacion_destino=bodega
    )
    lote.refresh_from_db()
    return lote


@pytest.fixture
def embultar(en_bodega, bodega, zona_bultos, jefe_bodega):
    """Registra un embultaje del lote de sostenimiento a la zona de bultos; acepta cambios."""

    def hacer(**cambios):
        datos = {
            "lote": en_bodega,
            "ubicacion_origen": bodega,
            "ubicacion_destino": zona_bultos,
            "usuario": jefe_bodega,
            **cambios,
        }
        return registrar_embultaje(**datos)

    return hacer


@pytest.fixture
def cliente(db):
    return Cliente.objects.create(
        tipo_documento="NIT", numero_documento="901555444", razon_social="Pescadería El Puerto"
    )


@pytest.fixture
def con_existencia(datos_lote, gerente):
    """Crea un lote del producto con existencia, entrado hace `dias` días (orden FIFO)."""

    def crear(codigo, kg, ubicacion, dias=0, vence_en=60):
        lote = Lote.objects.create(
            codigo=codigo,
            origen="INVENTARIO_INICIAL",
            **{**datos_lote, "fecha_vencimiento": timezone.localdate() + timedelta(vence_en)},
        )
        registrar_movimiento(
            lote=lote,
            tipo="INVENTARIO_INICIAL",
            cantidad=kg,
            usuario=gerente,
            ubicacion_destino=ubicacion,
            fecha_hora=timezone.now() - timedelta(days=dias),
        )
        return lote

    return crear


@pytest.fixture
def pedido(cliente, producto, jefe_bodega):
    """Pedido de 60 kg del producto del conftest general."""
    nuevo = crear_pedido(cliente=cliente, fecha=timezone.localdate(), usuario=jefe_bodega)
    agregar_linea(pedido=nuevo, producto=producto, cantidad_solicitada="60", usuario=jefe_bodega)
    return nuevo
