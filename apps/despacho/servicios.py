"""Servicio de despacho mayorista y de traslado a punto de venta (RF-35 a RF-45).

Despachar un pedido alistado es un solo paso: en una transacción se crea el documento, cada
línea registra un movimiento DESPACHO_MAYORISTA que descuenta la existencia de inmediato y el
pedido queda DESPACHADO. La constancia de entrega (firma en pantalla o foto del papel
firmado) se registra después y no mueve inventario.

El traslado a punto de venta, en cambio, exige que el PDV destino verifique y acepte (RD-04):
al enviarlo no se mueve nada; al aceptarlo, en una sola transacción, sale de bodega por lote y
entra al PDV por producto (RN-30); al rechazarlo queda el motivo y bodega reenvía un documento
corregido. Toda escritura queda en auditoría (RF-10).
"""

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AccionAuditoria, Evidencia
from apps.auditoria.servicios import instantanea, registrar
from apps.despacho.consultas import candidatos_traslado
from apps.despacho.models import (
    DespachoDetalle,
    DespachoMayorista,
    EstadoTraslado,
    TipoDocumentoDespacho,
    TrasladoPdv,
    TrasladoPdvDetalle,
    TrasladoPdvObservacion,
)
from apps.embultaje.consultas import UBICACIONES_DE_ALISTAMIENTO
from apps.embultaje.models import AlistamientoDetalle, EstadoPedido, Pedido
from apps.inventario.models import Lote, TipoMovimiento
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import TipoUbicacion
from apps.puntoventa.models import TipoMovimientoPdv
from apps.puntoventa.servicios import registrar_movimiento_pdv

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


# --- Traslado a punto de venta (RF-38 a RF-45) -------------------------------


def ve_traslado(usuario, traslado):
    """Bodega y consulta ven todos; el administrador de PDV, solo los de su punto (RN-06)."""
    return usuario.ve_bodega or usuario.opera_punto_venta(traslado.ubicacion_destino)


def _exigir_decision(usuario, traslado):
    if not usuario.opera_punto_venta(traslado.ubicacion_destino):
        raise PermissionDenied(
            "Solo el administrador del punto de venta destino o el Gerente reciben el traslado."
        )


def _traslado_enviado(pk):
    traslado = (
        TrasladoPdv.objects.select_for_update()
        .select_related("ubicacion_origen", "ubicacion_destino")
        .get(pk=pk)
    )
    if traslado.estado != EstadoTraslado.ENVIADO:
        raise DespachoInvalido(
            f"El traslado {traslado.consecutivo} ya fue {traslado.get_estado_display().lower()}."
        )
    return traslado


@transaction.atomic
def crear_traslado(
    *, origen, destino, nombre_entrega, lineas, usuario, traslado_anterior=None, ip=None
):
    """Registra el envío a un PDV y lo deja visible para ese punto de inmediato (RF-38, RF-39).

    No mueve la existencia: lo enviado queda apartado hasta que el PDV acepte o rechace.
    `lineas` es una lista de diccionarios con `lote` y `cantidad`. Con `traslado_anterior`,
    es el reenvío corregido de un traslado rechazado (RF-44).
    """
    _exigir_operador(usuario)
    if origen.tipo not in UBICACIONES_DE_ALISTAMIENTO:
        raise DespachoInvalido(
            "El traslado sale de la zona de bultos, el cuarto de sostenimiento o el túnel."
        )
    if destino.tipo != TipoUbicacion.PUNTO_VENTA or not destino.activo:
        raise DespachoInvalido("El destino debe ser un punto de venta activo.")
    nombre_entrega = _texto(nombre_entrega, "El nombre de quien entrega")
    if not lineas:
        raise DespachoInvalido("El traslado necesita al menos un lote.")
    lotes = [datos["lote"].pk for datos in lineas]
    if len(set(lotes)) != len(lotes):
        raise DespachoInvalido("Cada lote va una sola vez en el traslado.")
    if traslado_anterior is not None:
        traslado_anterior = TrasladoPdv.objects.select_for_update().get(pk=traslado_anterior.pk)
        if traslado_anterior.estado != EstadoTraslado.RECHAZADO:
            raise DespachoInvalido("Solo se reenvía un traslado rechazado.")
        if traslado_anterior.reenvios.exists():
            raise DespachoInvalido(
                f"El traslado {traslado_anterior.consecutivo} ya tiene su reenvío."
            )

    # Se bloquean los lotes: dos envíos a la vez no apartan el mismo saldo.
    list(Lote.objects.select_for_update().filter(pk__in=lotes).values_list("pk"))
    disponibles = {c.lote.pk: c.disponible for c in candidatos_traslado(origen)}
    validadas = []
    for datos in lineas:
        lote = datos["lote"]
        cantidad = _decimal(datos.get("cantidad"), f"La cantidad del lote {lote}", LIMITE_KG)
        disponible = disponibles.get(lote.pk, CERO)
        if cantidad > disponible:
            raise DespachoInvalido(
                f"Del lote {lote} en {origen.nombre} solo hay {disponible} kg disponibles."
            )
        validadas.append((lote, cantidad))

    traslado = TrasladoPdv.objects.create(
        consecutivo=f"TMP-{uuid4().hex[:16]}",
        fecha=timezone.localdate(),
        ubicacion_origen=origen,
        ubicacion_destino=destino,
        usuario_responsable=usuario,
        nombre_entrega=nombre_entrega,
        traslado_anterior=traslado_anterior,
    )
    traslado.consecutivo = f"T-{traslado.pk:06d}"
    traslado.save(update_fields=["consecutivo"])
    for lote, cantidad in validadas:
        TrasladoPdvDetalle.objects.create(traslado_pdv=traslado, lote=lote, cantidad=cantidad)
    _auditar(usuario, traslado, AccionAuditoria.CREAR, ip)
    return traslado


def _verificadas(detalles, verificadas):
    """Lo pesado en el PDV, una cifra por cada línea del traslado (RF-42)."""
    if set(verificadas) != {d.pk for d in detalles}:
        raise DespachoInvalido("Pese y registre todas las líneas del traslado.")
    return {
        d.pk: _decimal(
            verificadas[d.pk], f"El peso del lote {d.lote}", LIMITE_KG, permite_cero=True
        )
        for d in detalles
    }


@transaction.atomic
def aceptar_traslado(*, traslado, usuario, nombre_coincide, verificadas, ip=None):
    """Acepta el traslado y mueve la existencia de bodega al PDV (RF-41, RF-42, RN-28, RN-30).

    Solo se acepta si quien entrega es quien dice el documento y si cada línea pesa lo
    declarado; si no, la persona debe rechazarlo. Por línea, en una sola transacción, sale de
    bodega un TRASLADO_PDV por lote y entra al PDV un ENTRADA_TRASLADO por producto.
    """
    traslado = _traslado_enviado(traslado.pk)
    _exigir_decision(usuario, traslado)
    if not nombre_coincide:
        raise DespachoInvalido(
            "Si quien entrega no es la persona del documento, rechace el traslado (RF-41)."
        )
    detalles = list(traslado.detalles.select_related("lote__producto"))
    pesos = _verificadas(detalles, verificadas)
    distintas = [d.lote.codigo for d in detalles if pesos[d.pk] != d.cantidad]
    if distintas:
        raise DespachoInvalido(
            f"El peso no coincide en {', '.join(distintas)}: rechace el traslado con su "
            "observación (RN-28)."
        )

    anterior = instantanea(traslado)
    for detalle in detalles:
        registrar_movimiento(
            lote=detalle.lote,
            tipo=TipoMovimiento.TRASLADO_PDV,
            cantidad=detalle.cantidad,
            usuario=usuario,
            ubicacion_origen=traslado.ubicacion_origen,
            ubicacion_destino=traslado.ubicacion_destino,
        )
        registrar_movimiento_pdv(
            ubicacion=traslado.ubicacion_destino,
            producto=detalle.lote.producto,
            tipo=TipoMovimientoPdv.ENTRADA_TRASLADO,
            cantidad=detalle.cantidad,
            usuario=usuario,
        )
        detalle.cantidad_verificada = pesos[detalle.pk]
        detalle.save(update_fields=["cantidad_verificada"])
    traslado.estado = EstadoTraslado.ACEPTADO
    traslado.usuario_confirma = usuario
    traslado.fecha_hora_confirmacion = timezone.now()
    traslado.save(update_fields=["estado", "usuario_confirma", "fecha_hora_confirmacion"])
    _auditar(usuario, traslado, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return traslado


def _observar(traslado, usuario, observacion, ip):
    nota = TrasladoPdvObservacion.objects.create(
        traslado_pdv=traslado, usuario=usuario, observacion=observacion
    )
    _auditar(usuario, nota, AccionAuditoria.CREAR, ip)
    return nota


@transaction.atomic
def rechazar_traslado(*, traslado, usuario, observacion, verificadas=None, ip=None):
    """Rechaza el traslado: nada se mueve y queda el motivo por escrito (RF-43, RN-29).

    Si la persona alcanzó a pesar, lo pesado queda registrado como soporte del rechazo.
    """
    traslado = _traslado_enviado(traslado.pk)
    _exigir_decision(usuario, traslado)
    observacion = _texto(observacion, "El motivo del rechazo")
    if verificadas:
        detalles = list(traslado.detalles.select_related("lote"))
        pesos = _verificadas(detalles, verificadas)
        for detalle in detalles:
            detalle.cantidad_verificada = pesos[detalle.pk]
            detalle.save(update_fields=["cantidad_verificada"])

    anterior = instantanea(traslado)
    traslado.estado = EstadoTraslado.RECHAZADO
    traslado.usuario_confirma = usuario
    traslado.fecha_hora_confirmacion = timezone.now()
    traslado.save(update_fields=["estado", "usuario_confirma", "fecha_hora_confirmacion"])
    _observar(traslado, usuario, observacion, ip)
    _auditar(usuario, traslado, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return traslado


@transaction.atomic
def agregar_observacion(*, traslado, usuario, observacion, ip=None):
    """Nota de bodega, gerencia o el PDV destino mientras se revisa el caso (RF-43, RF-44)."""
    if not (usuario.puede_operar_bodega or usuario.opera_punto_venta(traslado.ubicacion_destino)):
        raise PermissionDenied("No participa en este traslado.")
    return _observar(traslado, usuario, _texto(observacion, "La observación"), ip)
