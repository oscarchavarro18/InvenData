"""Servicio de despacho mayorista (RF-35, RF-36, RF-37, RN-27, RD-04).

Despachar un pedido alistado es un solo paso: en una transacción se crea el documento, cada
línea registra un movimiento DESPACHO_MAYORISTA que descuenta la existencia de inmediato y el
pedido queda DESPACHADO. La constancia de entrega (firma en pantalla o foto del papel
firmado) se registra después y no mueve inventario. Toda escritura queda en auditoría.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Evidencia
from apps.auditoria.servicios import instantanea, registrar
from apps.despacho.models import DespachoDetalle, DespachoMayorista, TipoDocumentoDespacho
from apps.embultaje.models import AlistamientoDetalle, EstadoPedido, Pedido
from apps.inventario.models import TipoMovimiento
from apps.inventario.servicios import registrar_movimiento

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE_KG = Decimal("100000000")  # decimal(10,2)
LIMITE_VALOR = Decimal("10000000000")  # decimal(12,2)
LIMITE_BULTOS = 32767  # smallint
# Constancia de entrega: fotos o PDF del documento firmado, de tamaño razonable.
TIPOS_DE_EVIDENCIA = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
TAMANO_MAXIMO = 5 * 1024 * 1024
PUNTOS_MAXIMOS_FIRMA = 5000


class ErrorDespacho(Exception):
    """Base de los errores por reglas de negocio del despacho."""


class DespachoInvalido(ErrorDespacho):
    """La operación pedida rompe una regla (estado del pedido, datos, líneas...)."""


def _exigir_operador(usuario):
    if not usuario.puede_operar_bodega:
        raise PermissionDenied("Solo el Gerente y el Jefe de bodega despachan.")


def _texto(valor, nombre, obligatorio=True):
    texto = (valor or "").strip()
    if obligatorio and not texto:
        raise DespachoInvalido(f"{nombre} es obligatorio.")
    return texto or None


def _decimal(valor, nombre, limite, permite_cero=False):
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise DespachoInvalido(f"{nombre} no es un número válido.") from None
    if not numero.is_finite() or numero != numero.quantize(DOS_DECIMALES):
        raise DespachoInvalido(f"{nombre} debe tener como máximo dos decimales.")
    if numero < CERO or (numero == CERO and not permite_cero):
        raise DespachoInvalido(f"{nombre} debe ser mayor que cero.")
    if numero >= limite:
        raise DespachoInvalido(f"{nombre} es demasiado grande.")
    return numero


def _bultos(valor):
    if valor in (None, ""):
        return None
    try:
        bultos = int(str(valor).strip())
    except ValueError:
        raise DespachoInvalido("Los bultos o cajas deben ser un número entero.") from None
    if not 0 <= bultos <= LIMITE_BULTOS:
        raise DespachoInvalido("Los bultos o cajas deben estar entre 0 y 32767.")
    return bultos


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


@transaction.atomic
def despachar_pedido(
    *,
    pedido,
    usuario,
    placa_vehiculo,
    nombre_conductor,
    tipo_documento,
    numero_documento,
    lineas,
    numero_sello=None,
    valor_total=None,
    ip=None,
):
    """Registra el despacho de un pedido ALISTADO y descuenta la existencia (RF-35, RF-36).

    `lineas` trae, por cada lote alistado del pedido, un diccionario con `alistamiento`
    (el AlistamientoDetalle), `cantidad` (lo realmente cargado) y `cantidad_bultos_cajas`.
    Deben venir todas, una vez cada una. Devuelve el despacho creado.
    """
    _exigir_operador(usuario)
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if pedido.estado != EstadoPedido.ALISTADO:
        raise DespachoInvalido(
            f"El pedido {pedido.consecutivo} está {pedido.get_estado_display().lower()}: "
            "solo se despacha un pedido alistado."
        )
    if tipo_documento not in TipoDocumentoDespacho.values:
        raise DespachoInvalido("El tipo de documento debe ser factura o remisión.")
    numero_documento = _texto(numero_documento, "El número de documento")
    if DespachoMayorista.objects.filter(
        tipo_documento=tipo_documento, numero_documento=numero_documento
    ).exists():
        raise DespachoInvalido(
            f"Ya existe un despacho con "
            f"{TipoDocumentoDespacho(tipo_documento).label.lower()} {numero_documento}."
        )

    alistados = {
        detalle.pk: detalle
        for detalle in AlistamientoDetalle.objects.filter(pedido_linea__pedido=pedido)
        .select_related("lote", "ubicacion")
        .order_by("pk")
    }
    recibidos = [datos["alistamiento"].pk for datos in lineas]
    if sorted(recibidos) != sorted(alistados):
        raise DespachoInvalido(
            "El despacho debe incluir, una sola vez, cada lote alistado del pedido."
        )

    despacho = DespachoMayorista.objects.create(
        pedido=pedido,
        placa_vehiculo=_texto(placa_vehiculo, "La placa").upper(),
        numero_sello=_texto(numero_sello, "El sello", obligatorio=False),
        nombre_conductor=_texto(nombre_conductor, "El conductor"),
        tipo_documento=tipo_documento,
        numero_documento=numero_documento,
        valor_total=None
        if valor_total in (None, "")
        else _decimal(valor_total, "El valor total", LIMITE_VALOR, permite_cero=True),
        usuario_despacha=usuario,
    )
    for datos in lineas:
        alistamiento = alistados[datos["alistamiento"].pk]
        cantidad = _decimal(
            datos.get("cantidad"), f"La cantidad del lote {alistamiento.lote}", LIMITE_KG
        )
        registrar_movimiento(
            lote=alistamiento.lote,
            tipo=TipoMovimiento.DESPACHO_MAYORISTA,
            cantidad=cantidad,
            usuario=usuario,
            ubicacion_origen=alistamiento.ubicacion,
        )
        DespachoDetalle.objects.create(
            despacho_mayorista=despacho,
            alistamiento_detalle=alistamiento,
            cantidad_bultos_cajas=_bultos(datos.get("cantidad_bultos_cajas")),
            cantidad=cantidad,
        )

    anterior = instantanea(pedido)
    pedido.estado = EstadoPedido.DESPACHADO
    pedido.save(update_fields=["estado"])
    _auditar(usuario, despacho, AccionAuditoria.CREAR, ip)
    _auditar(usuario, pedido, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return despacho


def _validar_firma(firma):
    """La firma digital es una lista de trazos; cada trazo, una lista de puntos [x, y]."""
    if not isinstance(firma, list) or not firma:
        raise DespachoInvalido("La firma digital está vacía.")
    puntos = 0
    for trazo in firma:
        if not isinstance(trazo, list) or not trazo:
            raise DespachoInvalido("La firma digital no tiene un formato válido.")
        for punto in trazo:
            valido = (
                isinstance(punto, list)
                and len(punto) == 2
                and all(
                    isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 1000
                    for v in punto
                )
            )
            if not valido:
                raise DespachoInvalido("La firma digital no tiene un formato válido.")
        puntos += len(trazo)
    if puntos > PUNTOS_MAXIMOS_FIRMA:
        raise DespachoInvalido("La firma digital es demasiado larga.")
    return firma


@transaction.atomic
def registrar_entrega(*, despacho, usuario, nombre_recibe, firma=None, archivo=None, ip=None):
    """Deja constancia de quién recibió el despacho (RF-37); no mueve inventario.

    Se acepta la firma trazada en pantalla, la foto o PDF del documento firmado en papel, o
    ambas; al menos una. La foto queda en `evidencia` ligada a este despacho.
    """
    _exigir_operador(usuario)
    despacho = DespachoMayorista.objects.select_for_update().get(pk=despacho.pk)
    if despacho.fecha_hora_recepcion is not None:
        raise DespachoInvalido("El despacho ya tiene su constancia de entrega.")
    nombre_recibe = _texto(nombre_recibe, "El nombre de quien recibe")
    if firma is None and archivo is None:
        raise DespachoInvalido("Adjunte la foto del documento firmado o capture la firma.")
    if firma is not None:
        firma = _validar_firma(firma)
    if archivo is not None:
        tipo = getattr(archivo, "content_type", None)
        if tipo not in TIPOS_DE_EVIDENCIA:
            raise DespachoInvalido("La evidencia debe ser una foto (JPG, PNG o WebP) o un PDF.")
        if archivo.size > TAMANO_MAXIMO:
            raise DespachoInvalido("La evidencia no puede pesar más de 5 MB.")

    anterior = instantanea(despacho)
    despacho.nombre_recibe = nombre_recibe
    despacho.firma_recibe_digital = firma
    despacho.fecha_hora_recepcion = timezone.now()
    despacho.save(update_fields=["nombre_recibe", "firma_recibe_digital", "fecha_hora_recepcion"])
    if archivo is not None:
        evidencia = Evidencia.objects.create(
            entidad=DespachoMayorista._meta.db_table,
            registro_id=despacho.pk,
            archivo=archivo,
            tipo_mime=tipo,
            usuario=usuario,
        )
        registrar(
            usuario=usuario,
            entidad=Evidencia._meta.db_table,
            registro_id=evidencia.pk,
            accion=AccionAuditoria.CREAR,
            valor_nuevo={"entidad": evidencia.entidad, "registro_id": evidencia.registro_id},
            ip=ip,
        )
    _auditar(usuario, despacho, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return despacho
