"""Lecturas del tablero de inicio: la cadena del día y lo pendiente. Aquí no se modifica nada.

La cadena muestra, etapa por etapa, lo que se movió hoy y lo que está abierto. Los
pendientes son las tareas que esperan a alguien, con el enlace para resolverlas; cada perfil
ve solo lo que le corresponde y la acción dice si puede hacerla o solo consultarla (RF-02).
"""

from decimal import Decimal

from django.db.models import Count, Exists, Max, OuterRef, Sum
from django.urls import reverse
from django.utils import timezone

from apps.despacho.models import EstadoTraslado, TrasladoPdv
from apps.embultaje.models import EmbultajeRegistro, EstadoPedido, Pedido
from apps.inventario.consultas import kg_en_bodega, lotes_con_existencia
from apps.inventario.models import EstadoLote, Lote, Movimiento, TipoMovimiento
from apps.puntoventa.consultas import _rango
from apps.recepcion.models import DocumentoProveedor, EstadoDocumento
from apps.transformacion.models import EstadoOrden, OrdenTransformacion

CERO = Decimal("0")
MAXIMO_PENDIENTES = 12


def _movido_hoy(tipo):
    inicio, fin = _rango(timezone.localdate(), timezone.localdate())
    total = Movimiento.objects.filter(
        tipo=tipo, fecha_hora__gte=inicio, fecha_hora__lt=fin
    ).aggregate(t=Sum("cantidad"))["t"]
    return total or CERO


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def _lotes_por_cerrar():
    """Lotes con embultajes registrados que todavía no se cierran como embultados (RN-26)."""
    registros = EmbultajeRegistro.objects.filter(lote=OuterRef("pk"))
    return Lote.objects.filter(estado=EstadoLote.DISPONIBLE).filter(Exists(registros))


def _rechazados_sin_corregir():
    reenvios = TrasladoPdv.objects.filter(traslado_anterior=OuterRef("pk"))
    return TrasladoPdv.objects.filter(estado=EstadoTraslado.RECHAZADO).exclude(Exists(reenvios))


def cadena_del_dia():
    """Las seis etapas de la operación con lo movido hoy y lo que sigue abierto."""
    abiertos = DocumentoProveedor.objects.filter(estado=EstadoDocumento.ABIERTO).count()
    borradores = OrdenTransformacion.objects.filter(estado=EstadoOrden.BORRADOR).count()
    por_cerrar = _lotes_por_cerrar().count()
    enviados = TrasladoPdv.objects.filter(estado=EstadoTraslado.ENVIADO).count()
    alistados = Pedido.objects.filter(estado=EstadoPedido.ALISTADO).count()
    lotes = lotes_con_existencia().count()
    return [
        {
            "id": "recepcion",
            "paso": "01",
            "nombre": "Recepción",
            "kg": _movido_hoy(TipoMovimiento.RECEPCION),
            "nota": _plural(abiertos, "documento abierto", "documentos abiertos"),
            "alerta": False,
        },
        {
            "id": "almacen",
            "paso": "02",
            "nombre": "Almacén",
            "kg": kg_en_bodega(),
            "nota": _plural(lotes, "lote con existencia", "lotes con existencia"),
            "alerta": False,
        },
        {
            "id": "transformacion",
            "paso": "03",
            "nombre": "Transformación",
            "kg": _movido_hoy(TipoMovimiento.PRODUCCION_TRANSFORMACION),
            "nota": _plural(borradores, "orden en borrador", "órdenes en borrador"),
            "alerta": False,
        },
        {
            "id": "embultaje",
            "paso": "04",
            "nombre": "Embultaje",
            "kg": _movido_hoy(TipoMovimiento.EMBULTAJE),
            "nota": _plural(por_cerrar, "lote por cerrar", "lotes por cerrar"),
            "alerta": False,
        },
        {
            "id": "traslados",
            "paso": "05",
            "nombre": "Traslados a PDV",
            "kg": _movido_hoy(TipoMovimiento.TRASLADO_PDV),
            "nota": f"{enviados} por verificar",
            "alerta": enviados > 0,
        },
        {
            "id": "despacho",
            "paso": "06",
            "nombre": "Despacho",
            "kg": _movido_hoy(TipoMovimiento.DESPACHO_MAYORISTA),
            "nota": _plural(alistados, "pedido alistado", "pedidos alistados"),
            "alerta": False,
        },
    ]


def _pendiente(etapa, titulo, detalle, fecha, url, accion, tono="", principal=False):
    return {
        "etapa": etapa,
        "titulo": titulo,
        "detalle": detalle,
        "fecha": fecha,
        "url": url,
        "accion": accion,
        "tono": tono,
        "principal": principal,
    }


def pendientes(usuario):
    """Las tareas abiertas de la bodega y los traslados, las más recientes primero."""
    lista = []
    opera_recepcion = usuario.puede_operar_recepcion
    opera_bodega = usuario.puede_operar_bodega

    documentos = (
        DocumentoProveedor.objects.filter(estado=EstadoDocumento.ABIERTO)
        .select_related("proveedor")
        .annotate(n_lineas=Count("lineas"))
    )
    for doc in documentos:
        lista.append(
            _pendiente(
                "recepcion",
                f"Cerrar la recepción {doc}" if opera_recepcion else f"Recepción abierta {doc}",
                f"{doc.proveedor.razon_social} · {_plural(doc.n_lineas, 'línea', 'líneas')}",
                doc.creado_en,
                reverse("recepcion:documento_detalle", args=[doc.pk]),
                "Revisar y cerrar" if opera_recepcion else "Ver",
                principal=opera_recepcion,
            )
        )

    ordenes = OrdenTransformacion.objects.filter(estado=EstadoOrden.BORRADOR).select_related(
        "lote_origen__producto"
    )
    for orden in ordenes:
        lista.append(
            _pendiente(
                "transformacion",
                f"Confirmar la orden {orden.consecutivo}",
                f"{orden.lote_origen.producto.nombre} · {orden.cantidad_consumida} kg "
                f"del lote {orden.lote_origen.codigo}",
                orden.fecha_hora,
                reverse("transformacion:orden_detalle", args=[orden.pk]),
                "Confirmar" if opera_bodega else "Ver",
            )
        )

    lotes = (
        _lotes_por_cerrar()
        .select_related("producto")
        .annotate(ultimo=Max("registros_embultaje__fecha_hora"))
    )
    for lote in lotes:
        lista.append(
            _pendiente(
                "embultaje",
                f"Cerrar el lote embultado {lote.codigo}",
                f"{lote.producto.nombre} · lo que quede sin embultar pasa a merma",
                lote.ultimo,
                reverse(
                    "embultaje:lote_cerrar" if opera_bodega else "inventario:lote_detalle",
                    args=[lote.pk],
                ),
                "Cerrar lote" if opera_bodega else "Ver",
            )
        )

    enviados = TrasladoPdv.objects.filter(estado=EstadoTraslado.ENVIADO).select_related(
        "ubicacion_destino"
    )
    for traslado in enviados:
        decide = usuario.opera_punto_venta(traslado.ubicacion_destino)
        lista.append(
            _pendiente(
                "traslados",
                f"Verificar el traslado {traslado.consecutivo}",
                f"{traslado.ubicacion_destino.nombre} · lo entrega {traslado.nombre_entrega}",
                traslado.fecha_hora,
                reverse("despacho:traslado_detalle", args=[traslado.pk]),
                "Verificar" if decide else "Ver",
                tono="alerta",
                principal=decide,
            )
        )
    for traslado in _rechazados_sin_corregir().select_related("ubicacion_destino"):
        lista.append(
            _pendiente(
                "traslados",
                f"Corregir el traslado rechazado {traslado.consecutivo}",
                f"{traslado.ubicacion_destino.nombre} · rechazado al verificar",
                traslado.fecha_hora_confirmacion or traslado.fecha_hora,
                reverse("despacho:traslado_detalle", args=[traslado.pk]),
                "Corregir" if opera_bodega else "Ver",
                tono="grave",
            )
        )

    pedidos = Pedido.objects.filter(
        estado__in=(EstadoPedido.CREADO, EstadoPedido.ALISTADO)
    ).select_related("cliente")
    for pedido in pedidos:
        alistado = pedido.estado == EstadoPedido.ALISTADO
        if alistado and opera_bodega:
            url = reverse("despacho:despacho_crear", args=[pedido.pk])
        else:
            url = reverse("embultaje:pedido_detalle", args=[pedido.pk])
        lista.append(
            _pendiente(
                "despacho",
                f"Despachar el pedido {pedido.consecutivo}"
                if alistado
                else f"Alistar el pedido {pedido.consecutivo}",
                pedido.cliente.razon_social,
                pedido.fecha_hora_alistamiento if alistado else pedido.creado_en,
                url,
                ("Despachar" if alistado else "Alistar") if opera_bodega else "Ver",
                principal=alistado and opera_bodega,
            )
        )

    lista.sort(key=lambda p: p["fecha"].timestamp() if p["fecha"] else 0, reverse=True)
    return lista[:MAXIMO_PENDIENTES], len(lista)


def saludo():
    """Buenos días, buenas tardes o buenas noches según la hora local."""
    hora = timezone.localtime().hour
    if hora < 12:
        return "Buenos días"
    if hora < 19:
        return "Buenas tardes"
    return "Buenas noches"
