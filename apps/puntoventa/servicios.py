"""Servicio de movimientos del inventario de punto de venta (RF-48, RN-30, RNF-02, RNF-03).

Es el único camino para mover el inventario de un PDV: cada llamada deja el movimiento en el
libro y actualiza la existencia por producto, en una sola transacción, con el mismo patrón que
`apps.inventario.servicios.registrar_movimiento` en bodega. Nadie debe escribir en
MovimientoPuntoVenta ni en ExistenciaPuntoVenta por otra vía.

Hoy entran los traslados aceptados (ENTRADA_TRASLADO) y el inventario de arranque; las ventas
salen con VENTA. Los ajustes de gerencia (AJUSTE_CONTEO) llegan con M8, que define el sentido
de cada motivo en el punto de venta.

Las ventas (RF-46, RF-47) se registran en un solo paso: el documento, sus líneas y la salida
de cada producto van en una transacción (RN-31). La remisión a restaurante exige que el
cliente haya autorizado el tratamiento de sus datos (Ley 1581, RNF-01); si falta, quien
atiende la puede tomar en ese momento y queda registrada con su prueba.
"""

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import (
    guardar_evidencia,
    instantanea,
    registrar,
    validar_evidencia,
)
from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import (
    ExistenciaPuntoVenta,
    MovimientoPuntoVenta,
    TipoMovimientoPdv,
    VentaConsumidorFinal,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemision,
    VentaRestauranteRemisionLinea,
)

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo

# El signo de cada tipo sobre la existencia del PDV (DBML, nota de movimiento_punto_venta).
SUMAN = {TipoMovimientoPdv.ENTRADA_TRASLADO, TipoMovimientoPdv.INVENTARIO_INICIAL}
RESTAN = {TipoMovimientoPdv.VENTA}


class ErrorPuntoVenta(Exception):
    """Base de los errores por reglas de negocio del inventario de punto de venta."""


class MovimientoPdvInvalido(ErrorPuntoVenta):
    """El movimiento pedido rompe una regla (ubicación, tipo, cantidad...)."""


class ExistenciaPdvInsuficiente(ErrorPuntoVenta):
    """Se pidió sacar más de lo que hay: la existencia nunca queda negativa."""


def existencia_pdv(producto, ubicacion):
    """Cantidad actual del producto en el PDV; cero si nunca ha tenido."""
    cantidad = (
        ExistenciaPuntoVenta.objects.filter(producto=producto, ubicacion=ubicacion)
        .values_list("cantidad", flat=True)
        .first()
    )
    return CERO if cantidad is None else cantidad


def _validar_cantidad(cantidad):
    try:
        valor = Decimal(str(cantidad))
    except InvalidOperation:
        raise MovimientoPdvInvalido("La cantidad no es un número válido.") from None
    if not valor.is_finite():
        raise MovimientoPdvInvalido("La cantidad no es un número válido.")
    if valor <= CERO:
        raise MovimientoPdvInvalido("La cantidad debe ser mayor que cero.")
    if valor != valor.quantize(DOS_DECIMALES):
        raise MovimientoPdvInvalido("La cantidad admite como máximo dos decimales.")
    if valor >= LIMITE:
        raise MovimientoPdvInvalido("La cantidad es demasiado grande.")
    return valor


@transaction.atomic
def registrar_movimiento_pdv(*, ubicacion, producto, tipo, cantidad, usuario, fecha_hora=None):
    """Registra un movimiento del PDV y actualiza su existencia. Devuelve el movimiento."""
    if ubicacion.tipo != TipoUbicacion.PUNTO_VENTA:
        raise MovimientoPdvInvalido(f"{ubicacion.nombre} no es un punto de venta.")
    if tipo not in SUMAN | RESTAN:
        raise MovimientoPdvInvalido(f"El tipo {tipo!r} no se registra por esta vía.")
    cantidad = _validar_cantidad(cantidad)
    delta = cantidad if tipo in SUMAN else -cantidad

    # Se bloquea la fila: dos ventas o recepciones a la vez no se pisan.
    existencia, _ = ExistenciaPuntoVenta.objects.select_for_update().get_or_create(
        producto=producto, ubicacion=ubicacion, defaults={"cantidad": CERO}
    )
    if existencia.cantidad + delta < CERO:
        raise ExistenciaPdvInsuficiente(
            f"No hay existencia suficiente de {producto.nombre} en {ubicacion.nombre}: "
            f"disponible {existencia.cantidad}, solicitado {cantidad}."
        )
    existencia.cantidad += delta
    existencia.save(update_fields=["cantidad", "actualizado_en"])

    extra = {} if fecha_hora is None else {"fecha_hora": fecha_hora}
    return MovimientoPuntoVenta.objects.create(
        ubicacion=ubicacion,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        usuario=usuario,
        **extra,
    )


# --- Ventas (RF-46, RF-47, RN-31, RN-33) -------------------------------------


class VentaInvalida(ErrorPuntoVenta):
    """La venta pedida rompe una regla (líneas, factura, cliente, autorización...)."""


def _auditar(usuario, objeto, accion, ip, *, anterior=None):
    objeto.refresh_from_db()
    registrar(
        usuario=usuario,
        entidad=objeto._meta.db_table,
        registro_id=objeto.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=instantanea(objeto),
        ip=ip,
    )


def _exigir_vendedor(usuario, ubicacion):
    if ubicacion.tipo != TipoUbicacion.PUNTO_VENTA:
        raise VentaInvalida(f"{ubicacion.nombre} no es un punto de venta.")
    if not usuario.opera_punto_venta(ubicacion):
        raise PermissionDenied(
            "Solo el administrador de este punto de venta o el Gerente registran sus ventas."
        )


def _validar_lineas(lineas):
    """Al menos un producto, cada uno una sola vez y con una cantidad válida."""
    if not lineas:
        raise VentaInvalida("La venta necesita al menos un producto.")
    productos = [datos["producto"].pk for datos in lineas]
    if len(set(productos)) != len(productos):
        raise VentaInvalida("Cada producto va una sola vez: sume la cantidad en su línea.")
    try:
        return [(datos["producto"], _validar_cantidad(datos["cantidad"])) for datos in lineas]
    except MovimientoPdvInvalido as error:
        raise VentaInvalida(str(error)) from None


def _descontar(ubicacion, lineas, usuario, modelo_linea, campo_venta, venta):
    """Una línea y un movimiento VENTA por producto: la salida es inmediata (RN-31)."""
    for producto, cantidad in lineas:
        registrar_movimiento_pdv(
            ubicacion=ubicacion,
            producto=producto,
            tipo=TipoMovimientoPdv.VENTA,
            cantidad=cantidad,
            usuario=usuario,
        )
        modelo_linea.objects.create(**{campo_venta: venta}, producto=producto, cantidad=cantidad)


@transaction.atomic
def registrar_venta_consumidor(*, ubicacion, numero_factura_siigo, lineas, usuario, ip=None):
    """Venta a consumidor final ligada a la factura de Siigo (RF-46, RN-33, RD-01).

    `lineas` es una lista de diccionarios con `producto` y `cantidad`. Devuelve la venta.
    """
    _exigir_vendedor(usuario, ubicacion)
    factura = (numero_factura_siigo or "").strip().upper()
    if not factura:
        raise VentaInvalida("Escriba el número de la factura que generó Siigo.")
    if VentaConsumidorFinal.objects.filter(numero_factura_siigo=factura).exists():
        raise VentaInvalida(f"La factura {factura} ya está registrada en otra venta.")
    validadas = _validar_lineas(lineas)

    venta = VentaConsumidorFinal.objects.create(
        ubicacion=ubicacion,
        usuario=usuario,
        fecha=timezone.localdate(),
        numero_factura_siigo=factura,
    )
    _descontar(
        ubicacion, validadas, usuario, VentaConsumidorFinalLinea, "venta_consumidor_final", venta
    )
    _auditar(usuario, venta, AccionAuditoria.CREAR, ip)
    return venta


def _asegurar_autorizacion(cliente, usuario, autoriza, evidencia, ip):
    """El cliente debe haber autorizado el tratamiento de sus datos (Ley 1581, RNF-01).

    Si ya lo hizo, no se le vuelve a preguntar. Si no, quien atiende pregunta en ese momento:
    con su respuesta afirmativa se registra la autorización con la fecha de hoy y, si se
    adjunta, la foto del formato firmado como prueba.
    """
    if cliente.autoriza_tratamiento_datos:
        return
    if not autoriza:
        raise VentaInvalida(
            f"{cliente.razon_social} no ha autorizado el tratamiento de sus datos. Pregúntele "
            "y marque la autorización, o véndale como consumidor final."
        )
    if evidencia is not None:
        try:
            validar_evidencia(evidencia)
        except ValueError as error:
            raise VentaInvalida(str(error)) from None
    anterior = instantanea(cliente)
    cliente.autoriza_tratamiento_datos = True
    cliente.fecha_autorizacion = timezone.localdate()
    cliente.save(update_fields=["autoriza_tratamiento_datos", "fecha_autorizacion"])
    _auditar(usuario, cliente, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    if evidencia is not None:
        guardar_evidencia(
            entidad=cliente._meta.db_table,
            registro_id=cliente.pk,
            archivo=evidencia,
            usuario=usuario,
            ip=ip,
        )


@transaction.atomic
def registrar_venta_restaurante(
    *, ubicacion, cliente, lineas, usuario, autoriza_datos=False, evidencia=None, ip=None
):
    """Venta a restaurante con remisión propia, sin factura de Siigo (RF-47, RN-33).

    La remisión se numera sola (RM-000001). Devuelve la venta.
    """
    _exigir_vendedor(usuario, ubicacion)
    if not cliente.activo:
        raise VentaInvalida(f"El cliente {cliente.razon_social} está inactivo.")
    validadas = _validar_lineas(lineas)
    _asegurar_autorizacion(cliente, usuario, autoriza_datos, evidencia, ip)

    # Igual que el lote: el número sale del id, que la base entrega sin repetir.
    venta = VentaRestauranteRemision.objects.create(
        numero_documento=f"TMP-{uuid4().hex[:16]}",
        fecha=timezone.localdate(),
        ubicacion=ubicacion,
        cliente=cliente,
        usuario=usuario,
    )
    venta.numero_documento = f"RM-{venta.pk:06d}"
    venta.save(update_fields=["numero_documento"])
    _descontar(
        ubicacion,
        validadas,
        usuario,
        VentaRestauranteRemisionLinea,
        "venta_restaurante_remision",
        venta,
    )
    _auditar(usuario, venta, AccionAuditoria.CREAR, ip)
    return venta
