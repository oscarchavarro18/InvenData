"""Servicio de transformación y balance de masa (RF-23 a RF-29).

La orden nace en BORRADOR con su encabezado (lote de origen, ubicación y masa que se
consume) y en ese estado se puede corregir o eliminar sin tocar la existencia (RN-21). Al
confirmarla, en una sola transacción, se descuenta el origen, se crea un lote por cada
derivado con su movimiento de producción y se congela el balance de masa contra la
tolerancia vigente (RF-25 a RF-27). Toda escritura deja su rastro en auditoría (RF-10).
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.inventario.models import EstadoLote, EstadoProducto, Lote, OrigenLote, TipoMovimiento
from apps.inventario.servicios import existencia_de, registrar_movimiento
from apps.maestros.models import Parametro, TipoUbicacion
from apps.maestros.parametros import TOLERANCIA_BALANCE_PCT, leer_porcentaje
from apps.transformacion.models import EstadoOrden, OrdenTransformacion, TransformacionDerivado

CLAVE_TOLERANCIA = TOLERANCIA_BALANCE_PCT
CERO = Decimal("0")
CIEN = Decimal("100")
DOS_DECIMALES = Decimal("0.01")
LIMITE_KG = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo
LIMITE_PORCENTAJE = Decimal("1000")  # decimal(5,2): 3 enteros como máximo


class ErrorTransformacion(Exception):
    """Base de los errores por reglas de negocio de la transformación."""


class TransformacionInvalida(ErrorTransformacion):
    """La operación pedida rompe una regla (producto, estado, cantidades, tolerancia...)."""


@dataclass(frozen=True)
class Balance:
    """Balance de masa de una transformación (RF-25, RF-26, RF-27)."""

    masa_salida: Decimal
    merma_kg: Decimal
    porcentaje_cierre: Decimal
    dentro_tolerancia: bool


def _kg(valor, nombre):
    """Convierte a Decimal positivo con a lo sumo dos decimales, o falla con un mensaje claro."""
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise TransformacionInvalida(f"{nombre} no es un número válido.") from None
    if not numero.is_finite():
        raise TransformacionInvalida(f"{nombre} no es un número válido.")
    if numero <= CERO:
        raise TransformacionInvalida(f"{nombre} debe ser mayor que cero.")
    if numero != numero.quantize(DOS_DECIMALES):
        raise TransformacionInvalida(f"{nombre} admite como máximo dos decimales.")
    if numero >= LIMITE_KG:
        raise TransformacionInvalida(f"{nombre} es demasiado grande.")
    return numero


def tolerancia_vigente():
    """Porcentaje de tolerancia que configuró la gerencia en `parametro` (RF-27, RN-09)."""
    valor = Parametro.objects.filter(clave=CLAVE_TOLERANCIA).values_list("valor", flat=True).first()
    if valor is None:
        raise TransformacionInvalida(
            f"Falta el parámetro {CLAVE_TOLERANCIA}. El Gerente debe configurarlo."
        )
    try:
        return leer_porcentaje(valor)
    except ValueError:
        raise TransformacionInvalida(
            f"El parámetro {CLAVE_TOLERANCIA} debe ser un porcentaje entre 0 y 100."
        ) from None


def calcular_balance(cantidad_consumida, cantidades, tolerancia):
    """Masa de salida, merma, porcentaje de cierre y si queda dentro de la tolerancia.

    Lo normal es que salga menos de lo que entra (SN-21): el cierre está dentro si queda
    entre 100 − tolerancia y 100. Si sale más de lo que entró también se aparta y pide
    observación, porque indica un error de pesaje o de captura.
    """
    masa_salida = sum(cantidades, CERO)
    porcentaje = (masa_salida / cantidad_consumida * CIEN).quantize(
        DOS_DECIMALES, rounding=ROUND_HALF_UP
    )
    return Balance(
        masa_salida=masa_salida,
        merma_kg=cantidad_consumida - masa_salida,
        porcentaje_cierre=porcentaje,
        dentro_tolerancia=CIEN - tolerancia <= porcentaje <= CIEN,
    )


def _exigir_operador(usuario):
    if not usuario.puede_operar_bodega:
        raise PermissionDenied("Solo el Gerente y el Jefe de bodega operan la transformación.")


def _validar_origen(lote, ubicacion, cantidad):
    """Reglas del lote que se consume (RF-23, RN-24) y del lugar de donde sale."""
    if not lote.producto.admite_transformacion:
        raise TransformacionInvalida(
            f"El producto {lote.producto.nombre} no está marcado como transformable."
        )
    embultado = lote.estado == EstadoLote.EMBULTADO
    if embultado or lote.movimientos.filter(tipo=TipoMovimiento.EMBULTAJE).exists():
        raise TransformacionInvalida(
            f"El lote {lote.codigo} ya pasó por embultaje: no se puede transformar."
        )
    if ubicacion.tipo == TipoUbicacion.PUNTO_VENTA:
        raise TransformacionInvalida("La transformación consume producto de bodega, no de un PDV.")
    disponible = existencia_de(lote, ubicacion)
    if cantidad > disponible:
        raise TransformacionInvalida(
            f"No hay existencia suficiente del lote {lote.codigo} en {ubicacion.nombre}: "
            f"disponible {disponible}, solicitado {cantidad}."
        )


def _orden_en_borrador(pk):
    """Relee la orden bloqueándola; falla si ya no está en borrador."""
    orden = OrdenTransformacion.objects.select_for_update().select_related("lote_origen").get(pk=pk)
    if orden.estado != EstadoOrden.BORRADOR:
        raise TransformacionInvalida(f"La orden {orden.consecutivo} ya está confirmada.")
    return orden


def _auditar(usuario, objeto, accion, ip, *, anterior=None, registro_id=None):
    """Deja en auditoría lo que quedó guardado; va en la misma transacción (RF-10)."""
    if accion != AccionAuditoria.ANULAR:
        objeto.refresh_from_db()
    registrar(
        usuario=usuario,
        entidad=objeto._meta.db_table,
        registro_id=registro_id or objeto.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=None if accion == AccionAuditoria.ANULAR else instantanea(objeto),
        ip=ip,
    )


@transaction.atomic
def crear_orden(*, lote, ubicacion_origen, cantidad_consumida, usuario, ip=None):
    """Registra una orden en borrador (RF-23). No toca la existencia (RF-29)."""
    _exigir_operador(usuario)
    cantidad = _kg(cantidad_consumida, "La cantidad a consumir")
    lote = Lote.objects.select_related("producto").get(pk=lote.pk)
    _validar_origen(lote, ubicacion_origen, cantidad)

    # Igual que el lote: el consecutivo sale del id, que la base entrega sin repetir.
    orden = OrdenTransformacion.objects.create(
        consecutivo=f"TMP-{uuid4().hex[:16]}",
        lote_origen=lote,
        ubicacion_origen=ubicacion_origen,
        cantidad_consumida=cantidad,
        usuario=usuario,
    )
    orden.consecutivo = f"OT-{orden.pk:06d}"
    orden.save(update_fields=["consecutivo"])
    _auditar(usuario, orden, AccionAuditoria.CREAR, ip)
    return orden


@transaction.atomic
def editar_orden(*, orden, cantidad_consumida, usuario, ip=None):
    """Corrige la masa que se consumirá mientras la orden sigue en borrador."""
    _exigir_operador(usuario)
    orden = _orden_en_borrador(orden.pk)
    cantidad = _kg(cantidad_consumida, "La cantidad a consumir")
    _validar_origen(orden.lote_origen, orden.ubicacion_origen, cantidad)
    anterior = instantanea(orden)
    orden.cantidad_consumida = cantidad
    orden.save(update_fields=["cantidad_consumida"])
    _auditar(usuario, orden, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return orden


@transaction.atomic
def eliminar_orden(*, orden, usuario, ip=None):
    """Elimina una orden en borrador; queda constancia en auditoría como anulada."""
    _exigir_operador(usuario)
    orden = _orden_en_borrador(orden.pk)
    anterior, orden_id = instantanea(orden), orden.pk
    orden.delete()
    _auditar(usuario, orden, AccionAuditoria.ANULAR, ip, anterior=anterior, registro_id=orden_id)


def _validar_derivado(numero, datos, fecha_orden):
    """Revisa un derivado antes de crear nada. Devuelve sus datos ya normalizados."""
    producto = datos.get("producto")
    destino = datos.get("ubicacion_destino")
    estado_producto = datos.get("estado_producto")
    vencimiento = datos.get("fecha_vencimiento")
    if producto is None or not producto.activo:
        raise TransformacionInvalida(f"Derivado {numero}: elija un producto activo.")
    if destino is None or not destino.activo or destino.tipo == TipoUbicacion.PUNTO_VENTA:
        raise TransformacionInvalida(
            f"Derivado {numero}: el destino debe ser una zona de bodega activa."
        )
    if estado_producto not in EstadoProducto.values:
        raise TransformacionInvalida(f"Derivado {numero}: el estado debe ser fresco o congelado.")
    if not isinstance(vencimiento, date):
        raise TransformacionInvalida(f"Derivado {numero}: la fecha de vencimiento no es válida.")
    if vencimiento < fecha_orden:
        raise TransformacionInvalida(
            f"Derivado {numero}: no puede vencer antes de la fecha de la orden."
        )
    return {
        "producto": producto,
        "cantidad": _kg(datos.get("cantidad"), f"Derivado {numero}: la cantidad"),
        "ubicacion_destino": destino,
        "estado_producto": estado_producto,
        "fecha_vencimiento": vencimiento,
    }


def _crear_lote_derivado(orden, datos):
    """Lote nuevo para un derivado, ligado al lote de origen (RF-24, RF-28, RN-22)."""
    lote = Lote.objects.create(
        codigo=f"TMP-{uuid4().hex[:20]}",
        origen=OrigenLote.TRANSFORMACION,
        lote_origen=orden.lote_origen,
        producto=datos["producto"],
        estado_producto=datos["estado_producto"],
        fecha_vencimiento=datos["fecha_vencimiento"],
    )
    lote.codigo = f"L-{lote.pk:06d}"
    lote.save(update_fields=["codigo"])
    return lote


@transaction.atomic
def confirmar_orden(*, orden, derivados, usuario, observacion=None, ip=None):
    """Confirma la orden: único momento en que la transformación mueve existencias (RF-29).

    `derivados` es una lista de diccionarios con producto, cantidad, ubicacion_destino,
    estado_producto y fecha_vencimiento. Se descuenta el origen con CONSUMO_TRANSFORMACION,
    se crea un lote por derivado con su PRODUCCION_TRANSFORMACION y se congela el balance.
    Si el cierre se aparta de la tolerancia, la observación es obligatoria (RF-27, RN-20).
    """
    _exigir_operador(usuario)
    orden = _orden_en_borrador(orden.pk)
    if not derivados:
        raise TransformacionInvalida("La orden necesita al menos un derivado.")
    fecha_orden = timezone.localtime(orden.fecha_hora).date()
    validados = [
        _validar_derivado(n, datos, fecha_orden) for n, datos in enumerate(derivados, start=1)
    ]
    lote_origen = Lote.objects.select_related("producto").get(pk=orden.lote_origen_id)
    _validar_origen(lote_origen, orden.ubicacion_origen, orden.cantidad_consumida)

    balance = calcular_balance(
        orden.cantidad_consumida, [d["cantidad"] for d in validados], tolerancia_vigente()
    )
    if balance.masa_salida >= LIMITE_KG:
        raise TransformacionInvalida(
            "La masa de salida es demasiado grande: revise las cantidades."
        )
    if balance.porcentaje_cierre >= LIMITE_PORCENTAJE:
        raise TransformacionInvalida(
            "La masa de salida es más de diez veces la consumida: revise las cantidades."
        )
    observacion = (observacion or "").strip() or None
    if not balance.dentro_tolerancia and observacion is None:
        raise TransformacionInvalida(
            f"El cierre de {balance.porcentaje_cierre} % se aparta de la tolerancia: "
            "escriba una observación que explique la diferencia."
        )

    anterior = instantanea(orden)
    registrar_movimiento(
        lote=lote_origen,
        tipo=TipoMovimiento.CONSUMO_TRANSFORMACION,
        cantidad=orden.cantidad_consumida,
        usuario=usuario,
        ubicacion_origen=orden.ubicacion_origen,
    )
    for datos in validados:
        lote = _crear_lote_derivado(orden, datos)
        registrar_movimiento(
            lote=lote,
            tipo=TipoMovimiento.PRODUCCION_TRANSFORMACION,
            cantidad=datos["cantidad"],
            usuario=usuario,
            ubicacion_destino=datos["ubicacion_destino"],
        )
        derivado = TransformacionDerivado.objects.create(
            orden=orden,
            producto=datos["producto"],
            lote_derivado=lote,
            cantidad=datos["cantidad"],
            ubicacion_destino=datos["ubicacion_destino"],
        )
        _auditar(usuario, derivado, AccionAuditoria.CREAR, ip)

    orden.masa_salida = balance.masa_salida
    orden.merma_kg = balance.merma_kg
    orden.porcentaje_cierre = balance.porcentaje_cierre
    orden.dentro_tolerancia = balance.dentro_tolerancia
    orden.observacion = observacion
    orden.estado = EstadoOrden.CONFIRMADA
    orden.save(
        update_fields=[
            "masa_salida",
            "merma_kg",
            "porcentaje_cierre",
            "dentro_tolerancia",
            "observacion",
            "estado",
        ]
    )
    _auditar(usuario, orden, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return orden
