"""Servicio de conteo físico y de ajustes y reversos de gerencia (RF-09, RF-50 a RF-53).

El conteo solo deja constancia de lo contado: no mueve inventario (RN-36). Los ajustes y
reversos sí lo mueven, siempre por los servicios únicos de cada inventario
(`registrar_movimiento` en bodega y `registrar_movimiento_pdv` en el punto de venta), y solo
los registra el Gerente, con motivo y observación (RN-32, RN-34, RN-35). Aquí se agrega la
auditoría de cada uno en la misma transacción (RF-10).
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.conteo.models import ConteoFisico, ConteoFisicoDetalle
from apps.inventario.models import TipoMovimiento
from apps.inventario.servicios import registrar_movimiento, reversar_movimiento
from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import SentidoMovimientoPdv, TipoMovimientoPdv
from apps.puntoventa.servicios import registrar_movimiento_pdv, reversar_movimiento_pdv

LIMITE_BULTOS = 2147483647  # integer


class ErrorConteo(Exception):
    """Base de los errores por reglas de negocio del conteo físico."""


class ConteoInvalido(ErrorConteo):
    """El conteo pedido rompe una regla (líneas, fecha, ubicación...)."""


def _auditar(usuario, objeto, accion, ip):
    registrar(
        usuario=usuario,
        entidad=objeto._meta.db_table,
        registro_id=objeto.pk,
        accion=accion,
        valor_nuevo=instantanea(objeto),
        ip=ip,
    )


def es_punto_venta(ubicacion):
    return ubicacion.tipo == TipoUbicacion.PUNTO_VENTA


def puede_contar(usuario, ubicacion):
    """Bodega la cuenta el Gerente o el Jefe de bodega; un PDV, su administrador o el Gerente."""
    if es_punto_venta(ubicacion):
        return usuario.opera_punto_venta(ubicacion)
    return usuario.puede_operar_bodega


def ve_conteo(usuario, ubicacion):
    if es_punto_venta(ubicacion):
        return usuario.ve_punto_venta(ubicacion)
    return usuario.ve_bodega


@transaction.atomic
def registrar_conteo(*, ubicacion, fecha, lineas, usuario, ip=None):
    """Registra la jornada de conteo con sus bultos por producto (RF-50, RF-51).

    `lineas` es una lista de diccionarios con `producto` y `cantidad_bultos`. No mueve la
    existencia (RN-36). Devuelve el conteo.
    """
    if not puede_contar(usuario, ubicacion):
        raise PermissionDenied("No puede registrar conteos de esa ubicación.")
    if fecha > timezone.localdate():
        raise ConteoInvalido("La fecha del conteo no puede ser futura.")
    if not lineas:
        raise ConteoInvalido("El conteo necesita al menos un producto.")
    productos = [datos["producto"].pk for datos in lineas]
    if len(set(productos)) != len(productos):
        raise ConteoInvalido("Cada producto va una sola vez en el conteo.")
    for datos in lineas:
        bultos = datos["cantidad_bultos"]
        if not isinstance(bultos, int) or not 0 <= bultos <= LIMITE_BULTOS:
            raise ConteoInvalido(
                f"Los bultos de {datos['producto'].nombre} deben ser un entero no negativo."
            )

    conteo = ConteoFisico.objects.create(ubicacion=ubicacion, fecha=fecha, usuario=usuario)
    for datos in lineas:
        ConteoFisicoDetalle.objects.create(
            conteo_fisico=conteo,
            producto=datos["producto"],
            cantidad_bultos=datos["cantidad_bultos"],
        )
    _auditar(usuario, conteo, AccionAuditoria.CREAR, ip)
    return conteo


@transaction.atomic
def ajustar_bodega(*, lote, ubicacion, sentido, cantidad, motivo, observacion, usuario, ip=None):
    """Ajuste manual del Gerente sobre la existencia de un lote en bodega (RF-53, RN-34).

    `sentido` es ENTRADA (suma en la ubicación) o SALIDA (resta de ella).
    """
    if sentido not in SentidoMovimientoPdv.values:
        raise ConteoInvalido("Indique si el ajuste suma o resta.")
    suma = sentido == SentidoMovimientoPdv.ENTRADA
    movimiento = registrar_movimiento(
        lote=lote,
        tipo=TipoMovimiento.AJUSTE_CONTEO,
        cantidad=cantidad,
        usuario=usuario,
        ubicacion_origen=None if suma else ubicacion,
        ubicacion_destino=ubicacion if suma else None,
        motivo_ajuste=motivo,
        observacion=observacion,
    )
    _auditar(usuario, movimiento, AccionAuditoria.CREAR, ip)
    return movimiento


@transaction.atomic
def ajustar_pdv(*, ubicacion, producto, sentido, cantidad, motivo, observacion, usuario, ip=None):
    """Ajuste manual del Gerente sobre la existencia de un producto en un PDV (RF-53, RN-32)."""
    movimiento = registrar_movimiento_pdv(
        ubicacion=ubicacion,
        producto=producto,
        tipo=TipoMovimientoPdv.AJUSTE_CONTEO,
        cantidad=cantidad,
        usuario=usuario,
        sentido=sentido,
        motivo_ajuste=motivo,
        observacion=observacion,
    )
    _auditar(usuario, movimiento, AccionAuditoria.CREAR, ip)
    return movimiento


@transaction.atomic
def reversar_bodega(*, movimiento, usuario, observacion, ip=None):
    """Reverso de un movimiento de bodega con ajustes inversos que lo preservan (RF-09)."""
    ajustes = reversar_movimiento(movimiento=movimiento, usuario=usuario, observacion=observacion)
    for ajuste in ajustes:
        _auditar(usuario, ajuste, AccionAuditoria.CREAR, ip)
    return ajustes


@transaction.atomic
def reversar_pdv(*, movimiento, usuario, observacion, ip=None):
    """Reverso de un movimiento del PDV; corrige, por ejemplo, una venta mal registrada."""
    ajuste = reversar_movimiento_pdv(
        movimiento=movimiento, usuario=usuario, observacion=observacion
    )
    _auditar(usuario, ajuste, AccionAuditoria.CREAR, ip)
    return ajuste
