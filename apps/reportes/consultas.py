"""Consultas de los reportes de M9 (RF-56 a RF-60, RF-63, RF-66). Aquí no se modifica nada.

Cada función recibe filtros ya validados y el alcance de quien consulta, y devuelve un
`Reporte` listo para la pantalla, el CSV y el PDF. El alcance se decide en la vista con los
mismos criterios del resto del sistema: la bodega la ve todo perfil menos el Administrador
de PDV (RN-06), y cada quien ve solo los puntos de venta que le corresponden (RN-07).
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.inventario.consultas import lotes_por_vencer
from apps.inventario.models import (
    EstadoLote,
    Existencia,
    MotivoAjuste,
    Movimiento,
    TipoMovimiento,
)
from apps.puntoventa.consultas import _rango
from apps.puntoventa.models import (
    ExistenciaPuntoVenta,
    MovimientoPuntoVenta,
    SentidoMovimientoPdv,
    TipoMovimientoPdv,
    VentaConsumidorFinalLinea,
    VentaRestauranteRemisionLinea,
)
from apps.reportes.reporte import Columna, Reporte, formatear

CERO = Decimal("0")
CIEN = Decimal("100")

CONSUMIDOR = "Consumidor final"
RESTAURANTE = "Restaurante"


def _porcentaje(parte, total):
    return (parte * CIEN / total) if total else CERO


def _periodo(desde, hasta):
    return f"{desde:%d/%m/%Y} a {hasta:%d/%m/%Y}"


def _nombres(puntos):
    nombres = [p.nombre for p in puntos]
    return ", ".join(nombres) if len(nombres) <= 3 else f"Todos ({len(nombres)})"


# --- Existencias de bodega (RF-56, RF-63) ---------------------------------------------------


def existencias_bodega(*, ubicacion=None, producto=None, estado=None):
    """Existencia actual de bodega por ubicación y lote, con su vencimiento (RF-56)."""
    existencias = Existencia.objects.filter(cantidad__gt=0).select_related(
        "lote__producto", "ubicacion"
    )
    if ubicacion is not None:
        existencias = existencias.filter(ubicacion=ubicacion)
    if producto is not None:
        existencias = existencias.filter(lote__producto=producto)
    if estado:
        existencias = existencias.filter(lote__estado=estado)
    existencias = existencias.order_by(
        "ubicacion__codigo", "lote__fecha_vencimiento", "lote__codigo"
    )

    hoy = timezone.localdate()
    filas = []
    for existencia in existencias:
        lote = existencia.lote
        filas.append(
            {
                "ubicacion": existencia.ubicacion.nombre,
                "lote": lote.codigo,
                "producto": lote.producto.nombre,
                "estado_producto": lote.get_estado_producto_display(),
                "estado": lote.get_estado_display(),
                "vence": lote.fecha_vencimiento,
                "dias": (lote.fecha_vencimiento - hoy).days,
                "kg": existencia.cantidad,
            }
        )
    total = sum((f["kg"] for f in filas), CERO)
    por_producto = defaultdict(lambda: CERO)
    for fila in filas:
        por_producto[fila["producto"]] += fila["kg"]
    mayor = max(por_producto.items(), key=lambda par: par[1], default=None)

    resumen = [
        ("Existencia total", total, "kg"),
        ("Lotes", len({f["lote"] for f in filas}), "entero"),
        ("Productos", len(por_producto), "entero"),
        ("Ubicaciones", len({f["ubicacion"] for f in filas}), "entero"),
        ("Lotes vencidos", len({f["lote"] for f in filas if f["dias"] < 0}), "entero"),
    ]
    if mayor:
        participacion = formatear(_porcentaje(mayor[1], total), "porcentaje")
        resumen.append(("Mayor existencia", f"{mayor[0]} ({participacion})", "texto"))
    filtros = [
        ("Ubicación", ubicacion.nombre if ubicacion else "Todas las de bodega"),
        ("Producto", producto.nombre if producto else "Todos"),
        ("Estado del lote", dict(EstadoLote.choices).get(estado, "Todos")),
    ]
    return Reporte(
        titulo="Existencias de bodega",
        archivo="existencias-bodega",
        columnas=[
            Columna("ubicacion", "Ubicación"),
            Columna("lote", "Lote"),
            Columna("producto", "Producto"),
            Columna("estado_producto", "Estado del producto"),
            Columna("estado", "Estado del lote"),
            Columna("vence", "Vence", "fecha"),
            Columna("dias", "Días para vencer", "entero"),
            Columna("kg", "Kg", "kg"),
        ],
        filas=filas,
        filtros=filtros,
        resumen=resumen,
        totales={"ubicacion": "Total", "kg": total},
        nota="Corte a la fecha y hora de generación. Días negativos: el lote ya venció.",
    )


# --- Existencias de punto de venta (RF-57) --------------------------------------------------


def existencias_pdv(*, puntos, producto=None):
    """Existencia actual de cada punto de venta por producto, sin lote (RF-57, SN-09)."""
    existencias = ExistenciaPuntoVenta.objects.filter(
        ubicacion__in=puntos, cantidad__gt=0
    ).select_related("producto", "ubicacion")
    if producto is not None:
        existencias = existencias.filter(producto=producto)
    existencias = existencias.order_by("ubicacion__codigo", "producto__nombre")

    filas = [
        {
            "ubicacion": e.ubicacion.nombre,
            "codigo": e.producto.codigo,
            "producto": e.producto.nombre,
            "kg": e.cantidad,
            "actualizado": e.actualizado_en,
        }
        for e in existencias
    ]
    total = sum((f["kg"] for f in filas), CERO)
    for fila in filas:
        fila["participacion"] = _porcentaje(fila["kg"], total)
    return Reporte(
        titulo="Existencias de punto de venta",
        archivo="existencias-pdv",
        columnas=[
            Columna("ubicacion", "Punto de venta"),
            Columna("codigo", "Código"),
            Columna("producto", "Producto"),
            Columna("kg", "Kg", "kg"),
            Columna("participacion", "Participación", "porcentaje"),
            Columna("actualizado", "Último movimiento", "fechahora"),
        ],
        filas=filas,
        filtros=[
            ("Punto de venta", _nombres(puntos)),
            ("Producto", producto.nombre if producto else "Todos"),
        ],
        resumen=[
            ("Existencia total", total, "kg"),
            ("Productos", len({f["codigo"] for f in filas}), "entero"),
            ("Puntos con existencia", len({f["ubicacion"] for f in filas}), "entero"),
        ],
        totales={"ubicacion": "Total", "kg": total, "participacion": CIEN if filas else None},
        nota="Corte a la fecha y hora de generación. En el punto de venta no se maneja lote.",
    )


# --- Lotes vencidos y por vencer (RF-58) ----------------------------------------------------


def por_vencer(*, dias):
    """Lotes con existencia en bodega vencidos o que vencen en `dias` días o menos (RF-58)."""
    lotes = lotes_por_vencer(dias)
    donde = defaultdict(list)
    for existencia in (
        Existencia.objects.filter(lote__in=lotes, cantidad__gt=0)
        .select_related("ubicacion")
        .order_by("ubicacion__codigo")
    ):
        donde[existencia.lote_id].append(existencia.ubicacion.nombre)

    filas = []
    for lote in lotes:
        vencido = lote.dias_restantes < 0
        filas.append(
            {
                "situacion": "Vencido" if vencido else "Por vencer",
                "lote": lote.codigo,
                "producto": lote.producto.nombre,
                "estado_producto": lote.get_estado_producto_display(),
                "vence": lote.fecha_vencimiento,
                "dias": lote.dias_restantes,
                "kg": lote.kg,
                "ubicaciones": ", ".join(donde[lote.pk]),
                "vencido": vencido,
            }
        )
    vencidos = [f for f in filas if f["vencido"]]
    proximos = [f for f in filas if not f["vencido"]]
    total = sum((f["kg"] for f in filas), CERO)
    return Reporte(
        titulo="Lotes vencidos y por vencer",
        archivo="lotes-por-vencer",
        columnas=[
            Columna("situacion", "Situación"),
            Columna("lote", "Lote"),
            Columna("producto", "Producto"),
            Columna("estado_producto", "Estado del producto"),
            Columna("vence", "Vence", "fecha"),
            Columna("dias", "Días para vencer", "entero"),
            Columna("kg", "Kg", "kg"),
            Columna("ubicaciones", "Ubicación"),
        ],
        filas=filas,
        filtros=[("Horizonte", f"Vencidos y los que vencen en {dias} días o menos")],
        resumen=[
            ("Lotes vencidos", len(vencidos), "entero"),
            ("Kg vencidos", sum((f["kg"] for f in vencidos), CERO), "kg"),
            ("Lotes por vencer", len(proximos), "entero"),
            ("Kg por vencer", sum((f["kg"] for f in proximos), CERO), "kg"),
        ],
        totales={"situacion": "Total", "kg": total},
        nota="Ordenado por fecha de vencimiento: lo primero que vence es lo primero que sale.",
    )


# --- Ventas por punto, producto y canal (RF-59) ---------------------------------------------

AGRUPACIONES = {
    "detalle": ("Punto, producto y canal", ("ubicacion", "producto", "canal")),
    "producto": ("Producto", ("producto",)),
    "punto": ("Punto de venta", ("ubicacion",)),
    "canal": ("Canal", ("canal",)),
}
CANALES = {"": "Ambos canales", "CONSUMIDOR": CONSUMIDOR, "RESTAURANTE": RESTAURANTE}

# Por canal: el modelo de línea, el campo que lleva a la venta y su código en el filtro.
_FUENTES = (
    (CONSUMIDOR, VentaConsumidorFinalLinea, "venta_consumidor_final", "CONSUMIDOR"),
    (RESTAURANTE, VentaRestauranteRemisionLinea, "venta_restaurante_remision", "RESTAURANTE"),
)


def _lineas(modelo, venta, *, puntos, desde, hasta, producto):
    lineas = modelo.objects.filter(
        **{f"{venta}__ubicacion__in": puntos, f"{venta}__fecha__range": (desde, hasta)}
    )
    return lineas.filter(producto=producto) if producto is not None else lineas


def ventas(*, puntos, desde, hasta, producto=None, canal="", agrupar="detalle"):
    """Kg vendidos y número de ventas por punto, producto y canal en un periodo (RF-59).

    Consumidor final (factura de Siigo, RF-46) y restaurante (remisión, RF-47). Cada fila
    trae su participación sobre el total vendido del periodo.
    """
    titulo_grupo, claves = AGRUPACIONES.get(agrupar, AGRUPACIONES["detalle"])
    juntas = defaultdict(lambda: [CERO, 0])  # clave → [kg, ventas]
    por_canal = {CONSUMIDOR: CERO, RESTAURANTE: CERO}
    numero = {CONSUMIDOR: 0, RESTAURANTE: 0}
    por_producto = defaultdict(lambda: CERO)

    for nombre, modelo, venta, codigo in _FUENTES:
        if canal not in ("", codigo):
            continue
        lineas = _lineas(modelo, venta, puntos=puntos, desde=desde, hasta=hasta, producto=producto)
        campos = {"ubicacion": f"{venta}__ubicacion__nombre", "producto": "producto__nombre"}
        agrupados = [campos[c] for c in claves if c in campos]
        medidas = {"kg": Sum("cantidad"), "ventas": Count(venta, distinct=True)}
        if agrupados:
            grupos = lineas.values(*agrupados).annotate(**medidas).order_by()
        else:
            grupos = [lineas.aggregate(**medidas)]
        for grupo in grupos:
            if not grupo["kg"]:
                continue
            clave = tuple((c, nombre if c == "canal" else grupo[campos[c]]) for c in claves)
            # Un mismo producto o punto puede venir de los dos canales: se juntan. Las
            # ventas de canales distintos son documentos distintos, así que también se suman.
            juntas[clave][0] += grupo["kg"]
            juntas[clave][1] += grupo["ventas"]
        por_canal[nombre] = lineas.aggregate(t=Sum("cantidad"))["t"] or CERO
        numero[nombre] = lineas.values(venta).distinct().count()
        for fila in lineas.values("producto__nombre").annotate(kg=Sum("cantidad")).order_by():
            por_producto[fila["producto__nombre"]] += fila["kg"]

    total = sum(por_canal.values(), CERO)
    total_ventas = sum(numero.values())
    filas = []
    for clave, (kg, n) in juntas.items():
        fila = dict(clave)
        fila.update(kg=kg, ventas=n, participacion=_porcentaje(kg, total))
        filas.append(fila)
    filas.sort(key=lambda f: (-f["kg"], *(str(f[c]) for c in claves)))
    mas_vendido = max(por_producto.items(), key=lambda par: par[1], default=None)

    titulos = {"ubicacion": "Punto de venta", "producto": "Producto", "canal": "Canal"}
    columnas = [Columna(c, titulos[c]) for c in claves] + [
        Columna("ventas", "Ventas", "entero"),
        Columna("kg", "Kg vendidos", "kg"),
        Columna("participacion", "Participación", "porcentaje"),
    ]
    resumen = [
        ("Kg vendidos", total, "kg"),
        ("Ventas registradas", total_ventas, "entero"),
        ("Kg promedio por venta", (total / total_ventas) if total_ventas else CERO, "kg"),
        ("Kg a consumidor final", por_canal[CONSUMIDOR], "kg"),
        ("Kg a restaurantes", por_canal[RESTAURANTE], "kg"),
    ]
    if mas_vendido:
        resumen.append(("Producto más vendido", mas_vendido[0], "texto"))
    return Reporte(
        titulo="Ventas por punto de venta, producto y canal",
        archivo="ventas",
        columnas=columnas,
        filas=filas,
        filtros=[
            ("Periodo", _periodo(desde, hasta)),
            ("Punto de venta", _nombres(puntos)),
            ("Producto", producto.nombre if producto else "Todos"),
            ("Canal", CANALES.get(canal, CANALES[""])),
            ("Agrupado por", titulo_grupo),
        ],
        resumen=resumen,
        totales={
            claves[0]: "Total",
            "ventas": total_ventas,
            "kg": total,
            "participacion": CIEN if filas else None,
        },
        nota=(
            "Consumidor final: ventas con factura de Siigo. Restaurante: ventas con remisión. "
            "Una venta con varios productos cuenta en cada producto; el total de ventas cuenta "
            "cada documento una sola vez."
        ),
    )


# --- Correcciones y ajustes (RF-60) ---------------------------------------------------------

AMBITOS = {"": "Bodega y puntos de venta", "BODEGA": "Bodega", "PDV": "Punto de venta"}


def correcciones(*, ver_bodega, puntos, desde, hasta, ambito="", motivo=""):
    """Ajustes del Gerente y reversos de bodega y de PDV en un periodo (RF-60, RN-34, RN-35).

    Cada fila dice qué se corrigió, en qué sentido, por qué motivo, quién y con qué
    justificación. Un reverso es un ajuste por error de registro que apunta al original.
    """
    inicio, fin = _rango(desde, hasta)
    filas = []
    if ver_bodega and ambito in ("", "BODEGA"):
        ajustes = Movimiento.objects.filter(
            tipo=TipoMovimiento.AJUSTE_CONTEO, fecha_hora__gte=inicio, fecha_hora__lt=fin
        ).select_related("lote__producto", "ubicacion_origen", "ubicacion_destino", "usuario")
        if motivo:
            ajustes = ajustes.filter(motivo_ajuste=motivo)
        for m in ajustes:
            suma = m.ubicacion_destino_id is not None
            filas.append(
                _fila_correccion(
                    m,
                    ambito="Bodega",
                    ubicacion=(m.ubicacion_destino if suma else m.ubicacion_origen).nombre,
                    lote=m.lote.codigo,
                    producto=m.lote.producto.nombre,
                    suma=suma,
                    reverso=m.movimiento_reversado_id is not None,
                )
            )
    if puntos and ambito in ("", "PDV"):
        ajustes = MovimientoPuntoVenta.objects.filter(
            tipo=TipoMovimientoPdv.AJUSTE_CONTEO,
            ubicacion__in=puntos,
            fecha_hora__gte=inicio,
            fecha_hora__lt=fin,
        ).select_related("producto", "ubicacion", "usuario")
        if motivo:
            ajustes = ajustes.filter(motivo_ajuste=motivo)
        for m in ajustes:
            filas.append(
                _fila_correccion(
                    m,
                    ambito="Punto de venta",
                    ubicacion=m.ubicacion.nombre,
                    lote="",
                    producto=m.producto.nombre,
                    suma=m.sentido == SentidoMovimientoPdv.ENTRADA,
                    reverso=m.movimiento_punto_venta_reversado_id is not None,
                )
            )
    filas.sort(key=lambda f: f["fecha"])

    sumado = sum((f["kg"] for f in filas if f["kg"] > 0), CERO)
    restado = sum((-f["kg"] for f in filas if f["kg"] < 0), CERO)
    por_motivo = defaultdict(lambda: CERO)
    for fila in filas:
        por_motivo[fila["motivo"]] += abs(fila["kg"])
    principal = max(por_motivo.items(), key=lambda par: par[1], default=None)
    resumen = [
        ("Ajustes", sum(1 for f in filas if f["clase"] == "Ajuste"), "entero"),
        ("Reversos", sum(1 for f in filas if f["clase"] == "Reverso"), "entero"),
        ("Kg sumados", sumado, "kg"),
        ("Kg restados", restado, "kg"),
        ("Efecto neto", sumado - restado, "kg"),
    ]
    if principal:
        resumen.append(("Motivo principal", principal[0], "texto"))
    return Reporte(
        titulo="Correcciones y ajustes de inventario",
        archivo="correcciones",
        columnas=[
            Columna("fecha", "Fecha y hora", "fechahora"),
            Columna("ambito", "Ámbito"),
            Columna("ubicacion", "Ubicación"),
            Columna("lote", "Lote"),
            Columna("producto", "Producto"),
            Columna("clase", "Clase"),
            Columna("motivo", "Motivo"),
            Columna("kg", "Kg (+ suma, - resta)", "kg"),
            Columna("usuario", "Registró"),
            Columna("observacion", "Justificación"),
        ],
        filas=filas,
        filtros=[
            ("Periodo", _periodo(desde, hasta)),
            ("Ámbito", _ambito(ambito, ver_bodega, bool(puntos))),
            ("Motivo", dict(MotivoAjuste.choices).get(motivo, "Todos")),
        ],
        resumen=resumen,
        totales={"fecha": "Efecto neto", "kg": sumado - restado},
        nota=(
            "Solo el Gerente registra ajustes y reversos (RN-34). Ningún movimiento se edita ni "
            "se borra: un reverso es un movimiento nuevo que deja la existencia como estaba."
        ),
    )


def _ambito(ambito, ver_bodega, ver_puntos):
    """Cómo se rotula el ámbito: quien ve uno solo no lo elige."""
    if ver_bodega and ver_puntos:
        return AMBITOS.get(ambito, AMBITOS[""])
    return AMBITOS["BODEGA"] if ver_bodega else AMBITOS["PDV"]


def _fila_correccion(m, *, ambito, ubicacion, lote, producto, suma, reverso):
    return {
        "fecha": m.fecha_hora,
        "ambito": ambito,
        "ubicacion": ubicacion,
        "lote": lote,
        "producto": producto,
        "clase": "Reverso" if reverso else "Ajuste",
        "motivo": m.get_motivo_ajuste_display(),
        "kg": m.cantidad if suma else -m.cantidad,
        "usuario": m.usuario.nombre_completo,
        "observacion": m.observacion or "",
    }


def periodo_por_defecto(dias=30):
    """Los últimos `dias` días hasta hoy, para los reportes por periodo."""
    hoy = timezone.localdate()
    return hoy - timedelta(days=dias - 1), hoy
