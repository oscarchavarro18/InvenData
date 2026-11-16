"""Servicio de embultaje, pedidos y alistamiento (RF-30 a RF-34, RN-23 a RN-26).

Registrar un embultaje mueve de una vez lo embultado del origen al destino con un movimiento
EMBULTAJE: no es un borrador, porque lo que se pesa ya está empacado. El documento del día
se crea solo con el primer registro de la jornada. Cerrar el lote lo marca EMBULTADO y da de
baja como merma lo que quedó en origen.

El alistamiento de un pedido es un plan de picking: aparta lotes para cada línea sin tocar la
existencia, que se descuenta al despachar (M6). Toda escritura deja su rastro en auditoría
(RF-10).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.embultaje.consultas import (
    UBICACIONES_DE_ALISTAMIENTO,
    candidatos_fifo,
    resumen_de_cierre,
)
from apps.embultaje.models import (
    AlistamientoDetalle,
    Bulto,
    DocumentoEmbultaje,
    EmbultajeRegistro,
    EstadoPedido,
    Pedido,
    PedidoLinea,
)
from apps.inventario.models import EstadoLote, Lote, OrigenLote, TipoMovimiento
from apps.inventario.servicios import existencia_de, registrar_movimiento
from apps.maestros.models import TipoUbicacion

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE_KG = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo
LIMITE_BULTOS = 32767  # smallint


class ErrorEmbultaje(Exception):
    """Base de los errores por reglas de negocio del embultaje."""


class EmbultajeInvalido(ErrorEmbultaje):
    """La operación pedida rompe una regla (lote, ubicaciones, cantidades...)."""


def _kg(valor, nombre):
    """Convierte a Decimal positivo con a lo sumo dos decimales, o falla con un mensaje claro."""
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise EmbultajeInvalido(f"{nombre} no es un número válido.") from None
    if not numero.is_finite():
        raise EmbultajeInvalido(f"{nombre} no es un número válido.")
    if numero <= CERO:
        raise EmbultajeInvalido(f"{nombre} debe ser mayor que cero.")
    if numero != numero.quantize(DOS_DECIMALES):
        raise EmbultajeInvalido(f"{nombre} admite como máximo dos decimales.")
    if numero >= LIMITE_KG:
        raise EmbultajeInvalido(f"{nombre} es demasiado grande.")
    return numero


def _exigir_operador(usuario):
    if not usuario.puede_operar_bodega:
        raise PermissionDenied("Solo el Gerente y el Jefe de bodega operan el embultaje.")


def _auditar(usuario, objeto, accion, ip, *, anterior=None, registro_id=None):
    """Deja en auditoría lo que quedó guardado; va en la misma transacción (RF-10).

    Al anular (borrar) se pasa el id aparte, porque el objeto ya no lo conserva, y no hay
    valor nuevo.
    """
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


def validar_lote_embultable(lote):
    """Un lote se embulta si está disponible y nunca se transformó (RN-23, RN-24)."""
    if lote.estado != EstadoLote.DISPONIBLE:
        raise EmbultajeInvalido(f"El lote {lote.codigo} ya se cerró como embultado.")
    if lote.origen == OrigenLote.TRANSFORMACION:
        raise EmbultajeInvalido(
            f"El lote {lote.codigo} viene de una transformación: no se embulta (RN-24)."
        )
    if lote.movimientos.filter(tipo=TipoMovimiento.CONSUMO_TRANSFORMACION).exists():
        raise EmbultajeInvalido(f"El lote {lote.codigo} ya se transformó: no se embulta (RN-24).")


def _validar_ubicaciones(origen, destino):
    if origen.tipo == TipoUbicacion.PUNTO_VENTA:
        raise EmbultajeInvalido("El embultaje sale de una zona de bodega, no de un PDV.")
    if origen.tipo == TipoUbicacion.ZONA_BULTOS:
        raise EmbultajeInvalido("El producto de la zona de bultos ya está embultado.")
    if destino.tipo == TipoUbicacion.PUNTO_VENTA or not destino.activo:
        raise EmbultajeInvalido("El destino debe ser una zona de bodega activa.")
    if origen.pk == destino.pk:
        raise EmbultajeInvalido("El origen y el destino no pueden ser la misma ubicación.")


def _total(usa_calculo_bultos, cantidad_bultos, peso_por_bulto, total_kilos):
    """Total embultado según el modo: por bultos se calcula; si no, se digita (RN-26)."""
    if usa_calculo_bultos:
        if cantidad_bultos is None or peso_por_bulto is None:
            raise EmbultajeInvalido("Por bultos se indican la cantidad y el peso de cada bulto.")
        try:
            cantidad = int(str(cantidad_bultos).strip())  # «2.5» o «abc» no son enteros
        except ValueError:
            raise EmbultajeInvalido("La cantidad de bultos debe ser un número entero.") from None
        if not 0 < cantidad <= LIMITE_BULTOS:
            raise EmbultajeInvalido("La cantidad de bultos debe estar entre 1 y 32767.")
        peso = _kg(peso_por_bulto, "El peso por bulto")
        total = peso * cantidad
        if total >= LIMITE_KG:
            raise EmbultajeInvalido("El total embultado es demasiado grande.")
        return cantidad, peso, total
    if cantidad_bultos is not None or peso_por_bulto is not None:
        raise EmbultajeInvalido("Con el total digitado no se indican bultos ni peso por bulto.")
    if total_kilos is None:
        raise EmbultajeInvalido("Indique el total embultado en kg.")
    return None, None, _kg(total_kilos, "El total embultado")


def documento_del_dia(usuario, fecha=None):
    """El documento de embultaje de la fecha; lo crea quien registra el primer embultaje."""
    documento, _ = DocumentoEmbultaje.objects.get_or_create(
        fecha=fecha or timezone.localdate(), defaults={"usuario": usuario}
    )
    return documento


@transaction.atomic
def registrar_embultaje(
    *,
    lote,
    ubicacion_origen,
    ubicacion_destino,
    usuario,
    usa_calculo_bultos=False,
    cantidad_bultos=None,
    peso_por_bulto=None,
    total_kilos=None,
    ip=None,
):
    """Registra una tanda embultada y mueve su total del origen al destino (RN-23, RN-26).

    Por bultos genera un bulto numerado por cada uno, con el vencimiento del lote (RF-30,
    RF-31). Devuelve el registro creado.
    """
    _exigir_operador(usuario)
    lote = Lote.objects.select_for_update().get(pk=lote.pk)
    validar_lote_embultable(lote)
    _validar_ubicaciones(ubicacion_origen, ubicacion_destino)
    if existencia_de(lote, ubicacion_origen) <= CERO:
        raise EmbultajeInvalido(
            f"El lote {lote.codigo} no tiene existencia en {ubicacion_origen.nombre}."
        )
    cantidad, peso, total = _total(usa_calculo_bultos, cantidad_bultos, peso_por_bulto, total_kilos)

    registrar_movimiento(
        lote=lote,
        tipo=TipoMovimiento.EMBULTAJE,
        cantidad=total,
        usuario=usuario,
        ubicacion_origen=ubicacion_origen,
        ubicacion_destino=ubicacion_destino,
    )
    registro = EmbultajeRegistro.objects.create(
        documento_embultaje=documento_del_dia(usuario),
        lote=lote,
        ubicacion_origen=ubicacion_origen,
        ubicacion_destino=ubicacion_destino,
        usa_calculo_bultos=bool(usa_calculo_bultos),
        cantidad_bultos=cantidad,
        peso_por_bulto=peso,
        total_kilos=total,
        usuario=usuario,
    )
    for _ in range(cantidad or 0):
        # El consecutivo sale del id, que la base entrega sin repetir.
        bulto = Bulto.objects.create(
            embultaje_registro=registro,
            consecutivo=f"TMP-{uuid4().hex[:16]}",
            peso=peso,
            fecha_vencimiento=lote.fecha_vencimiento,
        )
        bulto.consecutivo = f"B-{bulto.pk:06d}"
        bulto.save(update_fields=["consecutivo"])
    _auditar(usuario, registro, AccionAuditoria.CREAR, ip)
    return registro


@transaction.atomic
def cerrar_lote(*, lote, usuario, ip=None):
    """Marca el lote EMBULTADO cuando ya no queda nada por embultar.

    Lo que quedó en las zonas de origen es la merma del paso de embultar: se da de baja con
    un movimiento MERMA_EMBULTAJE por zona y su suma queda en merma_vs_origen_kg. La foto del
    cierre (total embultado y merma) no se recalcula después. Devuelve el lote cerrado.
    """
    _exigir_operador(usuario)
    lote = Lote.objects.select_for_update().get(pk=lote.pk)
    if lote.estado == EstadoLote.EMBULTADO:
        raise EmbultajeInvalido(f"El lote {lote.codigo} ya está cerrado como embultado.")
    resumen = resumen_de_cierre(lote)
    if not resumen.registros:
        raise EmbultajeInvalido(f"El lote {lote.codigo} no tiene embultajes registrados.")
    if resumen.pendiente:
        zonas = ", ".join(f"{e.ubicacion.nombre} ({e.cantidad} kg)" for e in resumen.pendiente)
        raise EmbultajeInvalido(
            f"El lote todavía tiene producto sin embultar en {zonas}. Embúltelo o trasládelo "
            "a la zona de donde se embulta antes de cerrar."
        )

    anterior = instantanea(lote)
    for residuo in resumen.residuos:
        registrar_movimiento(
            lote=lote,
            tipo=TipoMovimiento.MERMA_EMBULTAJE,
            cantidad=residuo.cantidad,
            usuario=usuario,
            ubicacion_origen=residuo.ubicacion,
        )
    lote.estado = EstadoLote.EMBULTADO
    lote.cerrado_en = timezone.now()
    lote.cerrado_por = usuario
    lote.total_embultado_kg = resumen.total_embultado
    lote.merma_vs_origen_kg = resumen.merma
    lote.save(
        update_fields=[
            "estado",
            "cerrado_en",
            "cerrado_por",
            "total_embultado_kg",
            "merma_vs_origen_kg",
        ]
    )
    _auditar(usuario, lote, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return lote


# --- Pedidos y alistamiento (RF-32 a RF-34) ----------------------------------


def _pedido_editable(pk):
    """Relee el pedido bloqueándolo; solo un pedido CREADO admite cambios."""
    pedido = Pedido.objects.select_for_update().get(pk=pk)
    if pedido.estado != EstadoPedido.CREADO:
        raise EmbultajeInvalido(
            f"El pedido {pedido.consecutivo} está {pedido.get_estado_display().lower()}: "
            "ya no admite cambios."
        )
    return pedido


@transaction.atomic
def crear_pedido(*, cliente, fecha, usuario, ip=None):
    """Registra el pedido de un cliente mayorista, todavía sin líneas (RF-32)."""
    _exigir_operador(usuario)
    if not cliente.activo:
        raise EmbultajeInvalido(f"El cliente {cliente.razon_social} está inactivo.")
    if not isinstance(fecha, date):
        raise EmbultajeInvalido("La fecha del pedido no es válida.")
    # Igual que el lote: el consecutivo sale del id, que la base entrega sin repetir.
    pedido = Pedido.objects.create(
        consecutivo=f"TMP-{uuid4().hex[:16]}", cliente=cliente, fecha=fecha, usuario_crea=usuario
    )
    pedido.consecutivo = f"P-{pedido.pk:06d}"
    pedido.save(update_fields=["consecutivo"])
    _auditar(usuario, pedido, AccionAuditoria.CREAR, ip)
    return pedido


@transaction.atomic
def agregar_linea(*, pedido, producto, cantidad_solicitada, usuario, ip=None):
    _exigir_operador(usuario)
    pedido = _pedido_editable(pedido.pk)
    if not producto.activo:
        raise EmbultajeInvalido(f"El producto {producto.nombre} está inactivo.")
    if pedido.lineas.filter(producto=producto).exists():
        raise EmbultajeInvalido(
            f"El pedido ya tiene una línea de {producto.nombre}: ajuste esa línea."
        )
    linea = PedidoLinea.objects.create(
        pedido=pedido,
        producto=producto,
        cantidad_solicitada=_kg(cantidad_solicitada, "La cantidad solicitada"),
    )
    _auditar(usuario, linea, AccionAuditoria.CREAR, ip)
    return linea


@transaction.atomic
def quitar_linea(*, linea, usuario, ip=None):
    _exigir_operador(usuario)
    _pedido_editable(linea.pedido_id)
    if linea.alistamientos.exists():
        raise EmbultajeInvalido("Quite primero los lotes asignados a la línea.")
    anterior, linea_id = instantanea(linea), linea.pk
    linea.delete()
    _auditar(usuario, linea, AccionAuditoria.ANULAR, ip, anterior=anterior, registro_id=linea_id)


def _pendiente(linea):
    asignado = linea.alistamientos.aggregate(total=Sum("cantidad"))["total"] or CERO
    return linea.cantidad_solicitada - asignado


def _bloquear_lotes(producto):
    """Bloquea los lotes del producto: dos personas no apartan a la vez el mismo saldo."""
    list(Lote.objects.select_for_update().filter(producto=producto).values_list("pk"))


@transaction.atomic
def asignar_lote(*, linea, lote, ubicacion, cantidad, usuario, justificacion=None, ip=None):
    """Cubre parte de una línea con un lote elegido por la persona (RF-33, RF-34, RN-25).

    Si no es el que sugiere FIFO, la justificación es obligatoria. No toca la existencia:
    solo aparta lo disponible (existencia menos lo comprometido en otros pedidos).
    """
    _exigir_operador(usuario)
    _pedido_editable(linea.pedido_id)
    linea = PedidoLinea.objects.select_related("producto").get(pk=linea.pk)
    if lote.producto_id != linea.producto_id:
        raise EmbultajeInvalido(
            f"El lote {lote.codigo} no es de {linea.producto.nombre}: no cubre esta línea."
        )
    if ubicacion.tipo not in UBICACIONES_DE_ALISTAMIENTO:
        raise EmbultajeInvalido(f"No se alista desde {ubicacion.nombre}.")
    if lote.fecha_vencimiento < timezone.localdate():
        raise EmbultajeInvalido(f"El lote {lote.codigo} está vencido: no se alista.")
    cantidad = _kg(cantidad, "La cantidad")
    pendiente = _pendiente(linea)
    if cantidad > pendiente:
        raise EmbultajeInvalido(f"A la línea solo le faltan {pendiente} kg por cubrir.")

    _bloquear_lotes(linea.producto)
    candidatos = candidatos_fifo(linea.producto)
    elegido = next(
        (c for c in candidatos if (c.lote.pk, c.ubicacion.pk) == (lote.pk, ubicacion.pk)), None
    )
    disponible = CERO if elegido is None else elegido.disponible
    if cantidad > disponible:
        raise EmbultajeInvalido(
            f"Del lote {lote.codigo} en {ubicacion.nombre} solo hay {disponible} kg disponibles."
        )
    sugerido = candidatos[0] is elegido
    justificacion = (justificacion or "").strip() or None
    if not sugerido and justificacion is None:
        raise EmbultajeInvalido(
            f"FIFO sugiere el lote {candidatos[0].lote.codigo} en "
            f"{candidatos[0].ubicacion.nombre}: justifique por escrito si usa otro."
        )
    detalle = AlistamientoDetalle.objects.create(
        pedido_linea=linea,
        lote=lote,
        ubicacion=ubicacion,
        cantidad=cantidad,
        sugerido_por_fifo=sugerido,
        justificacion_cambio=None if sugerido else justificacion,
    )
    _auditar(usuario, detalle, AccionAuditoria.CREAR, ip)
    return detalle


@transaction.atomic
def sugerir_fifo(*, linea, usuario, ip=None):
    """Cubre lo que falta de la línea con los lotes más antiguos disponibles (RF-33, RN-25).

    Puede necesitar varios lotes (RF-34). Si no alcanza, cubre lo que haya. Devuelve los
    detalles creados.
    """
    _exigir_operador(usuario)
    _pedido_editable(linea.pedido_id)
    linea = PedidoLinea.objects.select_related("producto").get(pk=linea.pk)
    pendiente = _pendiente(linea)
    if pendiente <= CERO:
        raise EmbultajeInvalido("La línea ya está cubierta.")
    _bloquear_lotes(linea.producto)
    candidatos = candidatos_fifo(linea.producto)
    if not candidatos:
        raise EmbultajeInvalido(f"No hay {linea.producto.nombre} disponible para alistar.")
    detalles = []
    for candidato in candidatos:
        if pendiente <= CERO:
            break
        cantidad = min(pendiente, candidato.disponible)
        detalle = AlistamientoDetalle.objects.create(
            pedido_linea=linea,
            lote=candidato.lote,
            ubicacion=candidato.ubicacion,
            cantidad=cantidad,
            sugerido_por_fifo=True,
        )
        _auditar(usuario, detalle, AccionAuditoria.CREAR, ip)
        detalles.append(detalle)
        pendiente -= cantidad
    return detalles


@transaction.atomic
def quitar_alistamiento(*, detalle, usuario, ip=None):
    _exigir_operador(usuario)
    _pedido_editable(detalle.pedido_linea.pedido_id)
    anterior, detalle_id = instantanea(detalle), detalle.pk
    detalle.delete()
    _auditar(
        usuario, detalle, AccionAuditoria.ANULAR, ip, anterior=anterior, registro_id=detalle_id
    )


@transaction.atomic
def marcar_alistado(*, pedido, usuario, ip=None):
    """Da el pedido por alistado cuando cada línea tiene al menos un lote asignado (RF-34).

    La cobertura puede ser parcial: lo pesado no siempre cuadra con lo pedido.
    """
    _exigir_operador(usuario)
    pedido = _pedido_editable(pedido.pk)
    lineas = list(pedido.lineas.select_related("producto"))
    if not lineas:
        raise EmbultajeInvalido("El pedido no tiene líneas.")
    sin_lote = [linea.producto.nombre for linea in lineas if not linea.alistamientos.exists()]
    if sin_lote:
        raise EmbultajeInvalido(f"Falta asignar lotes a: {', '.join(sin_lote)}.")
    anterior = instantanea(pedido)
    pedido.estado = EstadoPedido.ALISTADO
    pedido.usuario_alista = usuario
    pedido.fecha_hora_alistamiento = timezone.now()
    pedido.save(update_fields=["estado", "usuario_alista", "fecha_hora_alistamiento"])
    _auditar(usuario, pedido, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return pedido


@transaction.atomic
def anular_pedido(*, pedido, usuario, observacion, ip=None):
    """Anula un pedido sin despachar; solo el Gerente, y siempre con el motivo escrito.

    Lo apartado queda libre para otros pedidos, porque un pedido anulado no compromete.
    """
    if not usuario.es_gerente:
        raise PermissionDenied("Solo el Gerente anula pedidos.")
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if pedido.estado not in (EstadoPedido.CREADO, EstadoPedido.ALISTADO):
        raise EmbultajeInvalido(
            f"El pedido {pedido.consecutivo} está {pedido.get_estado_display().lower()}: "
            "no se puede anular."
        )
    observacion = (observacion or "").strip()
    if not observacion:
        raise EmbultajeInvalido("Escriba por qué se anula el pedido.")
    anterior = instantanea(pedido)
    pedido.estado = EstadoPedido.ANULADO
    pedido.usuario_anula = usuario
    pedido.fecha_hora_anulacion = timezone.now()
    pedido.observacion_anulacion = observacion
    pedido.save(
        update_fields=["estado", "usuario_anula", "fecha_hora_anulacion", "observacion_anulacion"]
    )
    _auditar(usuario, pedido, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return pedido
