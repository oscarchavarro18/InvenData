"""Servicio de recepción de producto (RF-11 a RF-15).

Registrar una pesada no mueve inventario: solo deja constancia de lo que se pesó. La
existencia cambia al cerrar el documento del proveedor (RF-17), no antes. Mientras el
documento esté ABIERTO se pueden crear lotes y pesar tandas; una vez cerrado, nada más.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.inventario.models import EstadoProducto, Lote, OrigenLote, TipoMovimiento
from apps.inventario.servicios import registrar_movimiento
from apps.maestros.models import TipoUbicacion, Ubicacion
from apps.recepcion.models import (
    DocumentoProveedor,
    DocumentoProveedorLinea,
    EstadoDocumento,
    Recepcion,
    TipoDocumentoRecepcion,
)

# Adonde puede llegar el producto recién recibido (DBML: túnel, sostenimiento o, para cortar
# o reempacar de una vez, la zona de transformación). Ni punto de venta ni zona de bultos.
UBICACIONES_DE_RECEPCION = {
    TipoUbicacion.TUNEL_CONGELACION,
    TipoUbicacion.SOSTENIMIENTO,
    TipoUbicacion.ZONA_TRANSFORMACION,
}

CERO = Decimal("0")
DOS_DECIMALES = Decimal("0.01")
LIMITE_PESO = Decimal("100000000")  # decimal(10,2): 8 enteros como máximo
LIMITE_TEMPERATURA = Decimal("1000")  # decimal(5,2): 3 enteros como máximo


class ErrorRecepcion(Exception):
    """Base de los errores por reglas de negocio de la recepción."""


class RecepcionInvalida(ErrorRecepcion):
    """La operación pedida rompe una regla (documento cerrado, datos, ubicación...)."""


def _decimal(valor, nombre):
    """Convierte a Decimal con a lo sumo dos decimales, o falla con un mensaje claro."""
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise RecepcionInvalida(f"{nombre} no es un número válido.") from None
    if not numero.is_finite():
        raise RecepcionInvalida(f"{nombre} no es un número válido.")
    if numero != numero.quantize(DOS_DECIMALES):
        raise RecepcionInvalida(f"{nombre} admite como máximo dos decimales.")
    return numero


def _documento_abierto(documento_id):
    """Bloquea el documento y exige que siga ABIERTO, para no competir con su cierre."""
    documento = DocumentoProveedor.objects.select_for_update().get(pk=documento_id)
    if documento.estado != EstadoDocumento.ABIERTO:
        raise RecepcionInvalida("El documento ya está cerrado: no admite más lotes ni pesadas.")
    return documento


@transaction.atomic
def crear_documento(*, proveedor, tipo_documento, numero_documento, fecha):
    """Abre un documento del proveedor (factura o remisión) sin líneas todavía (RF-11)."""
    if not proveedor.activo:
        raise RecepcionInvalida("El proveedor está inactivo.")
    if tipo_documento not in TipoDocumentoRecepcion.values:
        raise RecepcionInvalida("El tipo de documento debe ser FACTURA o REMISION.")
    numero = (numero_documento or "").strip()
    if not numero:
        raise RecepcionInvalida("El número del documento es obligatorio.")
    if len(numero) > 30:
        raise RecepcionInvalida("El número del documento admite como máximo 30 caracteres.")
    if not isinstance(fecha, date):
        raise RecepcionInvalida("La fecha del documento no es una fecha válida.")

    ya_existe = RecepcionInvalida(
        f"Ya existe el documento {tipo_documento} {numero} de {proveedor.razon_social}."
    )
    if DocumentoProveedor.objects.filter(
        proveedor=proveedor, tipo_documento=tipo_documento, numero_documento=numero
    ).exists():
        raise ya_existe
    try:
        # Subtransacción: si otro usuario lo crea al mismo tiempo, la restricción única
        # de la base lo detiene y se responde con el mismo mensaje.
        with transaction.atomic():
            return DocumentoProveedor.objects.create(
                proveedor=proveedor,
                tipo_documento=tipo_documento,
                numero_documento=numero,
                fecha=fecha,
            )
    except IntegrityError:
        raise ya_existe from None


@transaction.atomic
def agregar_linea(*, documento, producto, cantidad):
    """Agrega un producto declarado a un documento abierto (RF-11, RF-15)."""
    _documento_abierto(documento.pk)
    if not producto.activo:
        raise RecepcionInvalida("El producto está inactivo.")
    declarada = _decimal(cantidad, "La cantidad")
    if declarada <= CERO:
        raise RecepcionInvalida("La cantidad debe ser mayor que cero.")
    if declarada >= LIMITE_PESO:
        raise RecepcionInvalida("La cantidad es demasiado grande.")
    if DocumentoProveedorLinea.objects.filter(documento_proveedor=documento, producto=producto):
        raise RecepcionInvalida(f"El producto {producto.nombre} ya está en el documento.")
    return DocumentoProveedorLinea.objects.create(
        documento_proveedor=documento, producto=producto, cantidad=declarada
    )


@transaction.atomic
def eliminar_linea(*, linea):
    """Quita una línea de un documento abierto, si todavía no generó lotes."""
    _documento_abierto(linea.documento_proveedor_id)
    if linea.lotes.exists():
        raise RecepcionInvalida("La línea ya tiene lotes: elimínelos antes de quitarla.")
    linea.delete()


@transaction.atomic
def crear_lote_recepcion(*, linea, estado_producto, fecha_vencimiento):
    """Crea un lote de recepción para una línea del documento (RF-11).

    Una línea puede generar varios lotes, por ejemplo si lo recibido trae fechas de
    vencimiento distintas. El lote nace sin existencia: esta llega al cerrar el documento.
    """
    documento = _documento_abierto(linea.documento_proveedor_id)
    if estado_producto not in EstadoProducto.values:
        raise RecepcionInvalida("El estado del producto debe ser FRESCO o CONGELADO.")
    if not isinstance(fecha_vencimiento, date):
        raise RecepcionInvalida("La fecha de vencimiento no es una fecha válida.")
    if fecha_vencimiento < documento.fecha:
        raise RecepcionInvalida("El producto no puede vencer antes de la fecha del documento.")

    # El código sale del id del lote, que la base entrega sin repetir ni siquiera con dos
    # recepciones simultáneas. Se crea con uno provisional y se reemplaza enseguida.
    lote = Lote.objects.create(
        codigo=f"TMP-{uuid4().hex[:20]}",
        origen=OrigenLote.RECEPCION,
        documento_proveedor_linea=linea,
        producto=linea.producto,
        estado_producto=estado_producto,
        fecha_vencimiento=fecha_vencimiento,
    )
    lote.codigo = f"L-{lote.pk:06d}"
    lote.save(update_fields=["codigo"])
    return lote


@transaction.atomic
def registrar_pesada(
    *,
    lote,
    tipo_embalaje,
    cantidad_embalajes,
    peso_bruto,
    temperatura,
    ubicacion_destino,
    usuario,
    fecha_hora=None,
):
    """Registra una tanda de pesada de un lote de recepción (RF-12, RF-13)."""
    if lote.origen != OrigenLote.RECEPCION or lote.documento_proveedor_linea_id is None:
        raise RecepcionInvalida("Solo se pesan lotes que vienen de una recepción.")
    _documento_abierto(lote.documento_proveedor_linea.documento_proveedor_id)

    if not tipo_embalaje.activo:
        raise RecepcionInvalida("El tipo de embalaje está inactivo.")
    if not ubicacion_destino.activo:
        raise RecepcionInvalida("La ubicación de destino está inactiva.")
    if ubicacion_destino.tipo not in UBICACIONES_DE_RECEPCION:
        raise RecepcionInvalida(
            f"{ubicacion_destino.nombre} no recibe producto: el destino debe ser un túnel, "
            "el cuarto de sostenimiento o la zona de transformación."
        )
    if isinstance(cantidad_embalajes, bool) or not isinstance(cantidad_embalajes, int):
        raise RecepcionInvalida("La cantidad de embalajes debe ser un número entero.")
    if cantidad_embalajes < 0:
        raise RecepcionInvalida("La cantidad de embalajes no puede ser negativa.")

    bruto = _decimal(peso_bruto, "El peso bruto")
    if bruto <= CERO:
        raise RecepcionInvalida("El peso bruto debe ser mayor que cero.")
    if bruto >= LIMITE_PESO:
        raise RecepcionInvalida("El peso bruto es demasiado grande.")
    grados = _decimal(temperatura, "La temperatura")
    if abs(grados) >= LIMITE_TEMPERATURA:
        raise RecepcionInvalida("La temperatura está fuera de rango.")

    tara = tipo_embalaje.peso_tara * cantidad_embalajes
    if bruto - tara <= CERO:
        raise RecepcionInvalida(
            f"La tara de los embalajes ({tara} kg) iguala o supera el peso bruto ({bruto} kg)."
        )

    return Recepcion.objects.create(
        lote=lote,
        tipo_embalaje=tipo_embalaje,
        responsable=usuario,
        ubicacion_destino=ubicacion_destino,
        fecha_hora=fecha_hora or timezone.now(),
        cantidad_embalajes=cantidad_embalajes,
        peso_bruto=bruto,
        temperatura=grados,
    )


def peso_recibido(linea):
    """Suma de peso_neto de todas las tandas de todos los lotes de la línea (RF-13, RF-15)."""
    total = Recepcion.objects.filter(lote__documento_proveedor_linea=linea).aggregate(
        total=Sum("peso_neto")
    )["total"]
    return CERO if total is None else total


def diferencia_de_linea(linea):
    """Lo declarado menos lo pesado: la merma de recepción, en vivo antes de cerrar (RF-15)."""
    return linea.cantidad - peso_recibido(linea)


@transaction.atomic
def eliminar_lote_sin_pesadas(*, lote):
    """Borra un lote de recepción creado por error que todavía no tiene ninguna pesada."""
    if lote.origen != OrigenLote.RECEPCION or lote.documento_proveedor_linea_id is None:
        raise RecepcionInvalida("Solo se eliminan lotes que vienen de una recepción.")
    _documento_abierto(lote.documento_proveedor_linea.documento_proveedor_id)
    if Recepcion.objects.filter(lote=lote).exists():
        raise RecepcionInvalida("El lote ya tiene pesadas: no se puede eliminar.")
    lote.delete()


@transaction.atomic
def cerrar_documento(*, documento, usuario):
    """Cierra el documento del proveedor y afecta las existencias (RF-15, RF-17).

    Todo ocurre en una sola transacción: si algo falla, el documento sigue abierto y no
    queda ningún movimiento. Por cada lote y ubicación de destino se registra un movimiento
    RECEPCION con la suma de sus tandas, y cada línea congela lo recibido y la diferencia
    contra lo declarado. Devuelve los movimientos creados.
    """
    documento = _documento_abierto(documento.pk)
    lineas = list(documento.lineas.all())
    if not lineas:
        raise RecepcionInvalida("El documento no tiene líneas.")

    del_documento = Lote.objects.filter(documento_proveedor_linea__documento_proveedor=documento)
    lotes = list(del_documento.annotate(n_tandas=Count("tandas")).order_by("codigo"))
    sin_pesadas = [lote.codigo for lote in lotes if lote.n_tandas == 0]
    if sin_pesadas:
        raise RecepcionInvalida(
            f"Hay lotes sin pesadas: {', '.join(sin_pesadas)}. "
            "Pese cada lote o elimínelo antes de cerrar."
        )

    # Lo pesado, sumado por lote y por ubicación de destino: un movimiento por cada par.
    grupos = list(
        Recepcion.objects.filter(lote__in=del_documento)
        .values("lote_id", "ubicacion_destino_id")
        .annotate(total=Sum("peso_neto"))
        .order_by("lote_id", "ubicacion_destino_id")
    )
    if not grupos:
        raise RecepcionInvalida("No se puede cerrar un documento sin ninguna pesada.")

    lote_por_id = {lote.pk: lote for lote in lotes}
    ubicaciones = Ubicacion.objects.in_bulk({g["ubicacion_destino_id"] for g in grupos})
    recibido_por_linea = defaultdict(lambda: CERO)
    movimientos = []
    for grupo in grupos:
        lote = lote_por_id[grupo["lote_id"]]
        recibido_por_linea[lote.documento_proveedor_linea_id] += grupo["total"]
        movimientos.append(
            registrar_movimiento(
                lote=lote,
                tipo=TipoMovimiento.RECEPCION,
                cantidad=grupo["total"],
                usuario=usuario,
                ubicacion_destino=ubicaciones[grupo["ubicacion_destino_id"]],
            )
        )

    # La foto de lo recibido queda fija: aunque después se reverse un movimiento, la
    # diferencia de recepción sigue siendo lo que se midió ese día.
    for linea in lineas:
        linea.cantidad_recibida = recibido_por_linea[linea.pk]
        linea.diferencia_kg = linea.cantidad - linea.cantidad_recibida
        linea.save(update_fields=["cantidad_recibida", "diferencia_kg"])

    documento.estado = EstadoDocumento.CERRADO
    documento.save(update_fields=["estado"])
    return movimientos
