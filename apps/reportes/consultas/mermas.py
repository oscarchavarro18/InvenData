"""Reporte consolidado de mermas (RF-55, RF-15, RF-25, RN-39).

Dos miradas. Por etapa: cuánto se perdió en el periodo al recibir, al transformar, al
embultar y por pérdidas o vencimientos. Por línea de recepción: la merma acumulada desde lo
que declaró el proveedor hasta lo que de verdad se aprovechó, sumando todos los lotes que
esa línea generó, también los derivados de sus transformaciones.
"""

from collections import defaultdict

from django.db.models import Exists, OuterRef, Sum

from apps.inventario.models import Lote, Movimiento, TipoMovimiento
from apps.puntoventa.consultas import _rango
from apps.recepcion.models import DocumentoProveedorLinea, EstadoDocumento
from apps.reportes.consultas.clasificacion import MOTIVOS_DE_MERMA
from apps.reportes.consultas.comun import CERO, periodo, porcentaje
from apps.reportes.reporte import Columna, Reporte, Seccion
from apps.transformacion.models import EstadoOrden, OrdenTransformacion

SUMABLES = (
    "lotes",
    "declarado",
    "recibido",
    "recepcion",
    "transformacion",
    "embultaje",
    "perdidas",
    "total",
    "aprovechado",
)


def _perdidas():
    """Ajustes por pérdida o vencimiento en bodega que no se reversaron."""
    reversos = Movimiento.objects.filter(movimiento_reversado=OuterRef("pk"))
    return Movimiento.objects.filter(
        tipo=TipoMovimiento.AJUSTE_CONTEO, motivo_ajuste__in=MOTIVOS_DE_MERMA
    ).exclude(Exists(reversos))


def _familias(raices):
    """Por cada lote raíz, él y todos sus derivados, de cualquier generación (RF-28)."""
    hijos = defaultdict(list)
    for pk, origen in Lote.objects.filter(lote_origen__isnull=False).values_list(
        "pk", "lote_origen"
    ):
        hijos[origen].append(pk)
    familias = {}
    for raiz in raices:
        familia, pendientes = set(), [raiz]
        while pendientes:
            actual = pendientes.pop()
            if actual not in familia:
                familia.add(actual)
                pendientes.extend(hijos[actual])
        familias[raiz] = familia
    return familias


def mermas_por_etapa(desde, hasta, producto):
    """Base, merma y número de eventos de cada etapa en el periodo."""
    inicio, fin = _rango(desde, hasta)
    lineas = DocumentoProveedorLinea.objects.filter(
        documento_proveedor__estado=EstadoDocumento.CERRADO,
        documento_proveedor__fecha__range=(desde, hasta),
    )
    ordenes = OrdenTransformacion.objects.filter(
        estado=EstadoOrden.CONFIRMADA, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    cerrados = Lote.objects.filter(cerrado_en__gte=inicio, cerrado_en__lt=fin)
    perdidas = _perdidas().filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
    if producto is not None:
        lineas = lineas.filter(producto=producto)
        ordenes = ordenes.filter(lote_origen__producto=producto)
        cerrados = cerrados.filter(producto=producto)
        perdidas = perdidas.filter(lote__producto=producto)

    def suma(consulta, campo):
        return consulta.aggregate(t=Sum(campo))["t"] or CERO

    embultado = suma(cerrados, "total_embultado_kg")
    merma_embultaje = suma(cerrados, "merma_vs_origen_kg")
    etapas = [
        (
            "Recepción",
            suma(lineas, "cantidad"),
            suma(lineas, "diferencia_kg"),
            lineas.count(),
            "Declarado por el proveedor contra lo pesado (RF-15).",
        ),
        (
            "Transformación",
            suma(ordenes, "cantidad_consumida"),
            suma(ordenes, "merma_kg"),
            ordenes.count(),
            "Masa consumida contra la suma de los derivados (RF-25).",
        ),
        (
            "Embultaje",
            embultado + merma_embultaje,
            merma_embultaje,
            cerrados.count(),
            "Lo que quedó sin embultar al cerrar cada lote (RN-26).",
        ),
        (
            "Pérdidas y vencimientos",
            None,
            suma(perdidas, "cantidad"),
            perdidas.count(),
            "Ajustes del Gerente por pérdida o vencimiento en bodega (RF-53).",
        ),
    ]
    filas = [
        {
            "etapa": etapa,
            "base": base,
            "merma": merma,
            "porcentaje": porcentaje(merma, base) if base else None,
            "eventos": eventos,
            "criterio": criterio,
        }
        for etapa, base, merma, eventos, criterio in etapas
    ]
    return filas, ordenes


def _por_linea(desde, hasta, producto):
    """La merma acumulada de cada línea de recepción cerrada en el periodo (RF-55)."""
    lineas = (
        DocumentoProveedorLinea.objects.filter(
            documento_proveedor__estado=EstadoDocumento.CERRADO,
            documento_proveedor__fecha__range=(desde, hasta),
        )
        .select_related("documento_proveedor__proveedor", "producto")
        .order_by("documento_proveedor__fecha", "documento_proveedor_id", "id")
    )
    if producto is not None:
        lineas = lineas.filter(producto=producto)
    lineas = list(lineas)
    raices = defaultdict(list)  # línea → sus lotes de recepción
    for pk, linea in Lote.objects.filter(documento_proveedor_linea__in=lineas).values_list(
        "pk", "documento_proveedor_linea"
    ):
        raices[linea].append(pk)
    familias = _familias([pk for lotes in raices.values() for pk in lotes])
    todos = set().union(*familias.values()) if familias else set()

    transformacion = defaultdict(lambda: CERO)
    for origen, merma in OrdenTransformacion.objects.filter(
        estado=EstadoOrden.CONFIRMADA, lote_origen__in=todos
    ).values_list("lote_origen", "merma_kg"):
        transformacion[origen] += merma or CERO
    embultaje = dict(
        Lote.objects.filter(pk__in=todos, merma_vs_origen_kg__isnull=False).values_list(
            "pk", "merma_vs_origen_kg"
        )
    )
    perdidas = defaultdict(lambda: CERO)
    agrupadas = _perdidas().filter(lote__in=todos).values("lote").annotate(kg=Sum("cantidad"))
    for g in agrupadas.order_by():
        perdidas[g["lote"]] += g["kg"]

    filas = []
    for linea in lineas:
        familia = set()
        for raiz in raices[linea.pk]:
            familia |= familias[raiz]
        recepcion = linea.diferencia_kg or CERO
        de_transformacion = sum((transformacion[pk] for pk in familia), CERO)
        de_embultaje = sum((embultaje.get(pk, CERO) for pk in familia), CERO)
        de_perdidas = sum((perdidas[pk] for pk in familia), CERO)
        total = recepcion + de_transformacion + de_embultaje + de_perdidas
        documento = linea.documento_proveedor
        filas.append(
            {
                "documento": (
                    f"{documento.get_tipo_documento_display()} {documento.numero_documento}"
                ),
                "fecha": documento.fecha,
                "proveedor": documento.proveedor.razon_social,
                "producto": linea.producto.nombre,
                "lotes": len(familia),
                "declarado": linea.cantidad,
                "recibido": linea.cantidad_recibida,
                "recepcion": recepcion,
                "transformacion": de_transformacion,
                "embultaje": de_embultaje,
                "perdidas": de_perdidas,
                "total": total,
                "aprovechado": linea.cantidad - total,
                "porcentaje": porcentaje(total, linea.cantidad),
            }
        )
    return filas


def mermas(*, desde, hasta, producto=None):
    """Mermas por etapa en el periodo y merma acumulada por línea de recepción (RF-55)."""
    etapas, ordenes = mermas_por_etapa(desde, hasta, producto)
    lineas = _por_linea(desde, hasta, producto)

    merma_periodo = sum((e["merma"] for e in etapas), CERO)
    mayor = max(etapas, key=lambda e: e["merma"])
    declarado = sum((f["declarado"] for f in lineas), CERO)
    total_lineas = sum((f["total"] for f in lineas), CERO)
    fuera = ordenes.filter(dentro_tolerancia=False).count()
    totales_lineas = {"documento": "Total"}
    for clave in SUMABLES:
        totales_lineas[clave] = sum((f[clave] or 0 for f in lineas), CERO)
    totales_lineas["porcentaje"] = porcentaje(total_lineas, declarado)

    detalle_ordenes = [
        {
            "orden": o.consecutivo,
            "fecha": o.fecha_hora,
            "lote": o.lote_origen.codigo,
            "producto": o.lote_origen.producto.nombre,
            "consumido": o.cantidad_consumida,
            "salida": o.masa_salida,
            "merma": o.merma_kg,
            "cierre": o.porcentaje_cierre,
            "tolerancia": "Sí" if o.dentro_tolerancia else "No",
            "observacion": o.observacion or "",
        }
        for o in ordenes.select_related("lote_origen__producto").order_by("fecha_hora")
    ]
    return Reporte(
        titulo="Reporte consolidado de mermas",
        archivo="mermas",
        columnas=[],
        filtros=[
            ("Periodo", periodo(desde, hasta)),
            ("Producto", producto.nombre if producto else "Todos"),
        ],
        resumen=[
            ("Merma del periodo", merma_periodo, "kg"),
            ("Etapa con más merma", mayor["etapa"] if mayor["merma"] > 0 else "Ninguna", "texto"),
            ("Declarado en el periodo", declarado, "kg"),
            ("Merma acumulada de esas líneas", total_lineas, "kg"),
            ("Aprovechado", declarado - total_lineas, "kg"),
            ("% de merma sobre lo declarado", porcentaje(total_lineas, declarado), "porcentaje"),
            ("Transformaciones fuera de tolerancia", f"{fuera} de {len(detalle_ordenes)}", "texto"),
        ],
        secciones=[
            Seccion(
                "Merma por etapa en el periodo",
                [
                    Columna("etapa", "Etapa"),
                    Columna("base", "Base (kg)", "kg"),
                    Columna("merma", "Merma (kg)", "kg"),
                    Columna("porcentaje", "% de merma", "porcentaje"),
                    Columna("eventos", "Registros", "entero"),
                    Columna("criterio", "Cómo se mide"),
                ],
                etapas,
                {"etapa": "Total", "merma": merma_periodo},
                nota="Una merma negativa en recepción indica que se pesó más de lo declarado.",
            ),
            Seccion(
                "Merma acumulada por línea de recepción",
                [
                    Columna("documento", "Documento"),
                    Columna("fecha", "Fecha", "fecha"),
                    Columna("proveedor", "Proveedor"),
                    Columna("producto", "Producto"),
                    Columna("lotes", "Lotes", "entero"),
                    Columna("declarado", "Declarado", "kg"),
                    Columna("recibido", "Recibido", "kg"),
                    Columna("recepcion", "Merma recepción", "kg"),
                    Columna("transformacion", "Merma transformación", "kg"),
                    Columna("embultaje", "Merma embultaje", "kg"),
                    Columna("perdidas", "Pérdidas y vencimientos", "kg"),
                    Columna("total", "Merma total", "kg"),
                    Columna("aprovechado", "Aprovechado", "kg"),
                    Columna("porcentaje", "% merma", "porcentaje"),
                ],
                lineas,
                totales_lineas if lineas else {},
                nota=(
                    "Líneas de documentos cerrados con fecha en el periodo. Suma la merma de "
                    "todos los lotes de la línea y de sus derivados hasta hoy. Aprovechado = "
                    "declarado - merma total."
                ),
            ),
            Seccion(
                "Transformaciones del periodo",
                [
                    Columna("orden", "Orden"),
                    Columna("fecha", "Fecha y hora", "fechahora"),
                    Columna("lote", "Lote de origen"),
                    Columna("producto", "Producto"),
                    Columna("consumido", "Consumido", "kg"),
                    Columna("salida", "Salida", "kg"),
                    Columna("merma", "Merma", "kg"),
                    Columna("cierre", "% de cierre", "porcentaje"),
                    Columna("tolerancia", "Dentro de tolerancia"),
                    Columna("observacion", "Observación"),
                ],
                detalle_ordenes,
            ),
        ],
        nota="Solo se leen datos ya registrados; ninguna cifra se captura aparte (RF-55).",
    )
