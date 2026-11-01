"""Indicadores de gestión (RF-61).

Se calculan con lo ya registrado, sin capturar nada aparte: merma del periodo, tiempo entre
la recepción y la salida de un lote, proporción de traslados rechazados, rendimiento de la
transformación, cumplimiento de FIFO, ventas y cobertura del inventario en los puntos de
venta. Cada indicador dice cómo se calcula, para que cualquiera pueda verificarlo.
"""

from django.db.models import Count, Exists, Max, Min, OuterRef, Q, Sum
from django.utils import timezone

from apps.despacho.models import DespachoDetalle, EstadoTraslado, TrasladoPdv, TrasladoPdvDetalle
from apps.embultaje.models import AlistamientoDetalle
from apps.inventario.models import Existencia, Lote, Movimiento, TipoMovimiento
from apps.puntoventa.consultas import _rango
from apps.puntoventa.models import (
    ExistenciaPuntoVenta,
    MovimientoPuntoVenta,
    TipoMovimientoPdv,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemisionLinea,
)
from apps.recepcion.models import DocumentoProveedorLinea, EstadoDocumento
from apps.reportes.consultas.clasificacion import MOTIVOS_DE_MERMA
from apps.reportes.consultas.comun import CERO, periodo, porcentaje
from apps.reportes.consultas.mermas import mermas_por_etapa
from apps.reportes.reporte import Columna, Reporte, formatear

INGRESOS = (
    TipoMovimiento.RECEPCION,
    TipoMovimiento.INVENTARIO_INICIAL,
    TipoMovimiento.PRODUCCION_TRANSFORMACION,
)


def _suma(consulta, campo):
    return consulta.aggregate(t=Sum(campo))["t"] or CERO


def _indicador(area, nombre, valor, tipo, detalle, formula, clave=None):
    return {
        "area": area,
        "indicador": nombre,
        "valor": formatear(valor, tipo) if valor is not None else "Sin datos",
        "detalle": detalle,
        "formula": formula,
        "clave": clave,  # las que van también como cifra clave arriba
        "crudo": (valor, tipo),
    }


def _bodega(desde, hasta, inicio, fin):
    etapas, ordenes = mermas_por_etapa(desde, hasta, None)
    merma = sum((e["merma"] for e in etapas), CERO)
    recepcion = etapas[0]
    lineas = DocumentoProveedorLinea.objects.filter(
        documento_proveedor__estado=EstadoDocumento.CERRADO,
        documento_proveedor__fecha__range=(desde, hasta),
    )
    declarado = _suma(lineas, "cantidad")
    consumido = _suma(ordenes, "cantidad_consumida")
    salida = _suma(ordenes, "masa_salida")
    n_ordenes = ordenes.count()
    fuera = ordenes.filter(dentro_tolerancia=False).count()

    # Lotes que se agotaron en el periodo: del primer ingreso al último movimiento.
    con_existencia = Existencia.objects.filter(lote=OuterRef("pk"), cantidad__gt=0)
    agotados = (
        Lote.objects.annotate(
            primero=Min("movimientos__fecha_hora", filter=Q(movimientos__tipo__in=INGRESOS)),
            ultimo=Max("movimientos__fecha_hora"),
        )
        .filter(primero__isnull=False, ultimo__gte=inicio, ultimo__lt=fin)
        .exclude(Exists(con_existencia))
        .values_list("primero", "ultimo")
    )
    dias = [(ultimo - primero).total_seconds() / 86400 for primero, ultimo in agotados]
    promedio = sum(dias) / len(dias) if dias else None

    decididos = TrasladoPdv.objects.filter(
        estado__in=(EstadoTraslado.ACEPTADO, EstadoTraslado.RECHAZADO),
        fecha_hora_confirmacion__gte=inicio,
        fecha_hora_confirmacion__lt=fin,
    )
    n_decididos = decididos.count()
    rechazados = decididos.filter(estado=EstadoTraslado.RECHAZADO).count()
    aceptado_kg = _suma(
        TrasladoPdvDetalle.objects.filter(
            traslado_pdv__in=decididos.filter(estado=EstadoTraslado.ACEPTADO)
        ),
        "cantidad",
    )
    despachos = DespachoDetalle.objects.filter(
        despacho_mayorista__fecha_hora__gte=inicio, despacho_mayorista__fecha_hora__lt=fin
    )
    n_despachos = despachos.values("despacho_mayorista").distinct().count()
    asignaciones = AlistamientoDetalle.objects.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
    n_asignaciones = asignaciones.count()
    por_fifo = asignaciones.filter(sugerido_por_fifo=True).count()

    existencia = _suma(Existencia.objects.filter(cantidad__gt=0), "cantidad")
    vencidas = Existencia.objects.filter(
        cantidad__gt=0, lote__fecha_vencimiento__lt=timezone.localdate()
    ).aggregate(kg=Sum("cantidad"), lotes=Count("lote", distinct=True))
    ajustes = Movimiento.objects.filter(
        tipo=TipoMovimiento.AJUSTE_CONTEO, fecha_hora__gte=inicio, fecha_hora__lt=fin
    )
    suma_ajustes = _suma(ajustes.filter(ubicacion_destino__isnull=False), "cantidad")
    resta_ajustes = _suma(ajustes.filter(ubicacion_origen__isnull=False), "cantidad")

    area = "Bodega"
    return [
        _indicador(
            area,
            "Merma total del periodo",
            merma,
            "kg",
            f"{formatear(porcentaje(merma, declarado), 'porcentaje')} de lo declarado "
            "por proveedores en el periodo",
            "Recepción + transformación + embultaje + pérdidas y vencimientos",
            clave="Merma del periodo",
        ),
        _indicador(
            area,
            "Merma de recepción",
            porcentaje(recepcion["merma"], declarado),
            "porcentaje",
            f"{formatear(recepcion['merma'], 'kg')} kg sobre {formatear(declarado, 'kg')} kg",
            "Diferencia entre lo declarado y lo pesado / lo declarado",
            clave="Merma de recepción",
        ),
        _indicador(
            area,
            "Rendimiento de transformación",
            porcentaje(salida, consumido) if consumido else None,
            "porcentaje",
            f"{n_ordenes} órdenes confirmadas",
            "Masa de salida / masa consumida (RF-26)",
            clave="Rendimiento de transformación",
        ),
        _indicador(
            area,
            "Transformaciones fuera de tolerancia",
            porcentaje(fuera, n_ordenes) if n_ordenes else None,
            "porcentaje",
            f"{fuera} de {n_ordenes} órdenes",
            "Órdenes cuyo cierre se apartó de la tolerancia / órdenes confirmadas (RF-27)",
        ),
        _indicador(
            area,
            "Tiempo entre recepción y salida de un lote",
            promedio,
            "dias",
            (
                f"Promedio de {len(dias)} lotes agotados; el más largo, "
                f"{formatear(max(dias), 'dias')} días"
            )
            if dias
            else "Ningún lote se agotó",
            "Del primer ingreso del lote a su último movimiento, en lotes ya agotados",
            clave="Días promedio en bodega",
        ),
        _indicador(
            area,
            "Traslados a punto de venta rechazados",
            porcentaje(rechazados, n_decididos) if n_decididos else None,
            "porcentaje",
            f"{rechazados} de {n_decididos} traslados decididos",
            "Traslados rechazados / traslados aceptados o rechazados (RF-43)",
            clave="Traslados rechazados",
        ),
        _indicador(
            area,
            "Kg trasladados a puntos de venta",
            aceptado_kg,
            "kg",
            f"{n_decididos - rechazados} traslados aceptados",
            "Suma de lo enviado en traslados aceptados",
        ),
        _indicador(
            area,
            "Kg despachados a mayoristas",
            _suma(despachos, "cantidad"),
            "kg",
            f"{n_despachos} despachos",
            "Suma de las líneas de despacho mayorista (RF-36)",
        ),
        _indicador(
            area,
            "Cumplimiento de FIFO en el alistamiento",
            porcentaje(por_fifo, n_asignaciones) if n_asignaciones else None,
            "porcentaje",
            f"{por_fifo} de {n_asignaciones} asignaciones siguieron la sugerencia",
            "Asignaciones con el lote sugerido por FIFO / asignaciones (RF-33, RNF-09)",
            clave="Cumplimiento FIFO",
        ),
        _indicador(
            area,
            "Existencia actual en bodega",
            existencia,
            "kg",
            "Corte a la fecha y hora de generación",
            "Suma de la existencia positiva de todos los lotes (RF-20)",
        ),
        _indicador(
            area,
            "Producto vencido en bodega",
            vencidas["kg"] or CERO,
            "kg",
            f"{vencidas['lotes']} lotes vencidos que todavía tienen existencia",
            "Existencia de lotes cuya fecha de vencimiento ya pasó (RF-58)",
        ),
        _indicador(
            area,
            "Ajustes del Gerente en bodega",
            suma_ajustes - resta_ajustes,
            "kg",
            f"{ajustes.count()} ajustes: {formatear(suma_ajustes, 'kg')} kg sumados y "
            f"{formatear(resta_ajustes, 'kg')} kg restados",
            "Kg sumados - kg restados por ajustes y reversos (RF-53, RF-09)",
        ),
    ]


def _puntos(puntos, desde, hasta, inicio, fin):
    consumidor = VentaConsumidorFinalLinea.objects.filter(
        venta_consumidor_final__ubicacion__in=puntos,
        venta_consumidor_final__fecha__range=(desde, hasta),
    )
    restaurante = VentaRestauranteRemisionLinea.objects.filter(
        venta_restaurante_remision__ubicacion__in=puntos,
        venta_restaurante_remision__fecha__range=(desde, hasta),
    )
    kg_consumidor = _suma(consumidor, "cantidad")
    kg_restaurante = _suma(restaurante, "cantidad")
    vendido = kg_consumidor + kg_restaurante
    ventas = (
        consumidor.values("venta_consumidor_final").distinct().count()
        + restaurante.values("venta_restaurante_remision").distinct().count()
    )
    dias = (hasta - desde).days + 1
    diario = vendido / dias
    existencia = _suma(
        ExistenciaPuntoVenta.objects.filter(ubicacion__in=puntos, cantidad__gt=0), "cantidad"
    )
    perdidas = _suma(
        MovimientoPuntoVenta.objects.filter(
            ubicacion__in=puntos,
            tipo=TipoMovimientoPdv.AJUSTE_CONTEO,
            motivo_ajuste__in=MOTIVOS_DE_MERMA,
            fecha_hora__gte=inicio,
            fecha_hora__lt=fin,
        ),
        "cantidad",
    )

    area = "Puntos de venta"
    return [
        _indicador(
            area,
            "Kg vendidos",
            vendido,
            "kg",
            f"{ventas} ventas; {formatear(diario, 'kg')} kg por día en promedio",
            "Suma de las líneas de venta a consumidor final y a restaurante (RF-59)",
            clave="Kg vendidos",
        ),
        _indicador(
            area,
            "Kg promedio por venta",
            (vendido / ventas) if ventas else None,
            "kg",
            f"{ventas} ventas en el periodo",
            "Kg vendidos / número de ventas",
        ),
        _indicador(
            area,
            "Participación de restaurantes",
            porcentaje(kg_restaurante, vendido) if vendido else None,
            "porcentaje",
            f"{formatear(kg_restaurante, 'kg')} kg por remisión y "
            f"{formatear(kg_consumidor, 'kg')} kg a consumidor final",
            "Kg vendidos a restaurantes / kg vendidos",
        ),
        _indicador(
            area,
            "Cobertura del inventario",
            (existencia / diario) if diario else None,
            "dias",
            f"{formatear(existencia, 'kg')} kg en vitrina hoy",
            "Existencia actual / venta diaria promedio del periodo",
            clave="Días de cobertura en PDV",
        ),
        _indicador(
            area,
            "Pérdidas y vencimientos en puntos de venta",
            perdidas,
            "kg",
            f"{formatear(porcentaje(perdidas, vendido), 'porcentaje')} de lo vendido"
            if vendido
            else "Sin ventas en el periodo",
            "Ajustes por pérdida o vencimiento en los puntos de venta (RF-53)",
        ),
    ]


def indicadores(*, ver_bodega, puntos, desde, hasta):
    """Los indicadores de gestión del periodo según lo que la persona puede ver (RF-61)."""
    inicio, fin = _rango(desde, hasta)
    filas = []
    if ver_bodega:
        filas += _bodega(desde, hasta, inicio, fin)
    if puntos:
        filas += _puntos(puntos, desde, hasta, inicio, fin)
    resumen = [(f["clave"], *f["crudo"]) for f in filas if f["clave"] and f["crudo"][0] is not None]
    return Reporte(
        titulo="Indicadores de gestión",
        archivo="indicadores",
        columnas=[
            Columna("area", "Área"),
            Columna("indicador", "Indicador"),
            Columna("valor", "Valor"),
            Columna("detalle", "Detalle"),
            Columna("formula", "Cómo se calcula"),
        ],
        filas=filas,
        filtros=[("Periodo", periodo(desde, hasta))],
        resumen=resumen,
        nota="Calculados con los datos ya registrados, sin captura adicional (RF-61).",
    )
