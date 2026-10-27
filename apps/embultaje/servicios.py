"""Servicio de embultaje (RF-30, RF-31, RN-23, RN-24, RN-26).

Registrar un embultaje mueve de una vez lo embultado del origen al destino con un movimiento
EMBULTAJE: no es un borrador, porque lo que se pesa ya está empacado. El documento del día
se crea solo con el primer registro de la jornada. Cerrar el lote lo marca EMBULTADO y da de
baja como merma lo que quedó en origen. Toda escritura deja su rastro en auditoría (RF-10).
"""

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.embultaje.consultas import resumen_de_cierre
from apps.embultaje.models import Bulto, DocumentoEmbultaje, EmbultajeRegistro
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


def _auditar(usuario, objeto, accion, ip, *, anterior=None):
    """Deja en auditoría lo que quedó guardado; va en la misma transacción (RF-10)."""
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
