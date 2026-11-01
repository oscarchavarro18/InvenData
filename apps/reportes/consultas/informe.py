"""Informe general de inventario por periodo y alcance (RF-63, RF-64, RF-65, RNF-03).

Todo se reconstruye desde los libros de movimientos (bodega y PDV), que son la fuente de
verdad: inventario inicial del periodo, entradas, salidas, traslados, mermas, ajustes e
inventario final. Si el periodo llega hasta hoy, el final calculado se compara con la
existencia registrada para verificar que la proyección cuadra con el libro.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import BooleanField, Case, Count, Q, Sum, Value, When
from django.utils import timezone

from apps.inventario.models import Existencia, Movimiento, TipoMovimiento
from apps.maestros.models import Producto, TipoUbicacion, Ubicacion
from apps.puntoventa.consultas import _rango, puntos_visibles
from apps.puntoventa.models import (
    ExistenciaPuntoVenta,
    MovimientoPuntoVenta,
    SentidoMovimientoPdv,
    TipoMovimientoPdv,
)
from apps.reportes.consultas.clasificacion import (
    AJUSTE,
    ENTRADA,
    MERMA,
    NOMBRES,
    SALIDA,
    TRASLADO,
    acumular,
    clase_bodega,
    clase_pdv,
    columnas_vacias,
    neto,
)
from apps.reportes.consultas.comun import CERO, periodo
from apps.reportes.reporte import Columna, Reporte, Seccion

TODA_LA_OPERACION = ""
TODA_LA_BODEGA = "BODEGA"
TODOS_LOS_PUNTOS = "PDV"

SUMABLES = ("inicial", "entradas", "salidas", "t_entran", "t_salen", "mermas", "ajustes", "final")
ORDEN_DE_CLASES = (ENTRADA, SALIDA, TRASLADO, MERMA, AJUSTE)
SIN_LOTE_EN_PDV = "El punto de venta no maneja lote: con un lote elegido solo cuenta la bodega."


@dataclass
class Alcance:
    """Qué ubicaciones entran en el informe (RF-65)."""

    etiqueta: str
    bodega: list = field(default_factory=list)  # ids de zonas de bodega
    puntos: list = field(default_factory=list)  # ids de puntos de venta


def _zonas():
    return Ubicacion.objects.exclude(tipo=TipoUbicacion.PUNTO_VENTA).order_by("codigo")


def opciones_de_alcance(usuario):
    """Los alcances que la persona puede pedir, el más amplio primero (RN-06, RN-07)."""
    puntos = list(puntos_visibles(usuario))
    opciones = []
    if usuario.ve_bodega and puntos:
        opciones.append((TODA_LA_OPERACION, "Toda la operación (bodega y puntos de venta)"))
    if usuario.ve_bodega:
        opciones.append((TODA_LA_BODEGA, "Toda la bodega"))
        opciones += [(f"U{z.pk}", f"Zona: {z.nombre}") for z in _zonas()]
    if len(puntos) > 1:
        opciones.append((TODOS_LOS_PUNTOS, "Todos los puntos de venta"))
    opciones += [(f"U{p.pk}", f"Punto de venta: {p.nombre}") for p in puntos]
    return opciones


def resolver_alcance(usuario, valor):
    """El alcance pedido si la persona puede verlo; si no, el más amplio que tiene."""
    opciones = dict(opciones_de_alcance(usuario))
    if not opciones:
        return None
    if valor not in opciones:
        valor = next(iter(opciones))
    bodega = list(_zonas().values_list("pk", flat=True)) if usuario.ve_bodega else []
    puntos = list(puntos_visibles(usuario).values_list("pk", flat=True))
    etiqueta = opciones[valor]
    if valor == TODA_LA_OPERACION:
        return Alcance(etiqueta, bodega, puntos)
    if valor == TODA_LA_BODEGA:
        return Alcance(etiqueta, bodega, [])
    if valor == TODOS_LOS_PUNTOS:
        return Alcance(etiqueta, [], puntos)
    pk = int(valor[1:])
    return Alcance(etiqueta, [pk], []) if pk in bodega else Alcance(etiqueta, [], [pk])


def _dentro(campo, ids):
    return Case(
        When(**{f"{campo}__in": ids}, then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    )


def _bodega(alcance, producto, lote):
    movimientos = Movimiento.objects.filter(
        Q(ubicacion_origen_id__in=alcance.bodega) | Q(ubicacion_destino_id__in=alcance.bodega)
    )
    if producto is not None:
        movimientos = movimientos.filter(lote__producto=producto)
    if lote is not None:
        movimientos = movimientos.filter(lote=lote)
    return movimientos.annotate(
        entra=_dentro("ubicacion_destino_id", alcance.bodega),
        sale=_dentro("ubicacion_origen_id", alcance.bodega),
    )


def _pdv(alcance, producto):
    movimientos = MovimientoPuntoVenta.objects.filter(ubicacion_id__in=alcance.puntos)
    if producto is not None:
        movimientos = movimientos.filter(producto=producto)
    return movimientos


def informe_general(*, alcance, desde, hasta, producto=None, lote=None):
    """Inventario inicial, movimientos clasificados e inventario final por producto (RF-64)."""
    inicio, fin = _rango(desde, hasta)
    # El punto de venta no maneja lote (SN-09): con un lote elegido solo cuenta la bodega.
    con_pdv = bool(alcance.puntos) and lote is None
    iniciales = defaultdict(lambda: CERO)
    filas = defaultdict(columnas_vacias)
    por_tipo = defaultdict(lambda: [CERO, 0])  # (ámbito, clase, tipo) → [kg, movimientos]

    if alcance.bodega:
        bodega = _bodega(alcance, producto, lote)
        antes = bodega.filter(fecha_hora__lt=inicio).values("lote__producto", "entra", "sale")
        for g in antes.annotate(kg=Sum("cantidad")).order_by():
            iniciales[g["lote__producto"]] += g["kg"] * (int(g["entra"]) - int(g["sale"]))
        durante = bodega.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin).values(
            "lote__producto", "tipo", "motivo_ajuste", "entra", "sale"
        )
        for g in durante.annotate(kg=Sum("cantidad"), n=Count("id")).order_by():
            clase = clase_bodega(g["tipo"], g["motivo_ajuste"])
            acumular(filas[g["lote__producto"]], clase, g["kg"], entra=g["entra"], sale=g["sale"])
            interno = g["entra"] and g["sale"]
            clave = ("Bodega", clase, _tipo_bodega(g["tipo"], interno))
            por_tipo[clave][0] += g["kg"]
            por_tipo[clave][1] += g["n"]

    if con_pdv:
        pdv = _pdv(alcance, producto)
        antes = pdv.filter(fecha_hora__lt=inicio).values("producto", "sentido")
        for g in antes.annotate(kg=Sum("cantidad")).order_by():
            signo = 1 if g["sentido"] == SentidoMovimientoPdv.ENTRADA else -1
            iniciales[g["producto"]] += signo * g["kg"]
        durante = pdv.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin).values(
            "producto", "tipo", "motivo_ajuste", "sentido"
        )
        for g in durante.annotate(kg=Sum("cantidad"), n=Count("id")).order_by():
            clase = clase_pdv(g["tipo"], g["motivo_ajuste"])
            entra = g["sentido"] == SentidoMovimientoPdv.ENTRADA
            acumular(filas[g["producto"]], clase, g["kg"], entra=entra, sale=not entra)
            clave = ("Punto de venta", clase, TipoMovimientoPdv(g["tipo"]).label)
            por_tipo[clave][0] += g["kg"]
            por_tipo[clave][1] += g["n"]

    # Verificación de cuadre: solo tiene sentido si el corte es hoy (RNF-03).
    verificar = hasta >= timezone.localdate()
    registradas = _registradas(alcance, producto, lote, con_pdv) if verificar else {}

    ids = set(iniciales) | set(filas) | set(registradas)
    productos = Producto.objects.in_bulk(ids)
    resumen_filas = []
    cuadran = 0
    for pk in ids:
        columnas = filas[pk]
        inicial = iniciales[pk]
        final = inicial + neto(columnas)
        registrada = registradas.get(pk, CERO) if verificar else None
        if not any([inicial, final, registrada, *columnas.values()]):
            continue
        cuadra = verificar and final == registrada
        cuadran += int(cuadra)
        resumen_filas.append(
            {
                "producto": productos[pk].nombre,
                "codigo": productos[pk].codigo,
                "inicial": inicial,
                **columnas,
                "final": final,
                "registrada": registrada,
                "cuadre": ("Cuadra" if cuadra else "Diferencia") if verificar else "No aplica",
            }
        )
    resumen_filas.sort(key=lambda f: f["producto"])
    totales = {"producto": "Total"}
    for clave in SUMABLES:
        totales[clave] = sum((f[clave] for f in resumen_filas), CERO)
    if verificar:
        totales["registrada"] = sum((f["registrada"] for f in resumen_filas), CERO)

    detalle = _detalle(alcance, producto, lote, con_pdv, inicio, fin)
    tipos = [
        {"ambito": a, "clase": NOMBRES[c], "tipo": t, "kg": kg, "n": n}
        for (a, c, t), (kg, n) in sorted(
            por_tipo.items(), key=lambda par: (ORDEN_DE_CLASES.index(par[0][1]), par[0])
        )
    ]

    if verificar:
        cuadre = f"Cuadra en {cuadran} de {len(resumen_filas)} productos"
    else:
        cuadre = "No aplica: el corte es anterior a hoy"
    filtros = [
        ("Periodo", periodo(desde, hasta)),
        ("Alcance", alcance.etiqueta),
        ("Producto", producto.nombre if producto else "Todos"),
        ("Lote", lote.codigo if lote else "Todos"),
    ]
    return Reporte(
        titulo="Informe general de inventario",
        archivo="informe-general",
        columnas=[],
        filtros=filtros,
        resumen=[
            ("Inventario inicial", totales["inicial"], "kg"),
            ("Entradas", totales["entradas"], "kg"),
            ("Salidas", totales["salidas"], "kg"),
            ("Traslados netos", totales["t_entran"] - totales["t_salen"], "kg"),
            ("Mermas", totales["mermas"], "kg"),
            ("Ajustes netos", totales["ajustes"], "kg"),
            ("Inventario final", totales["final"], "kg"),
            ("Verificación de cuadre", cuadre, "texto"),
        ],
        secciones=[
            Seccion(
                "Resumen por producto",
                [
                    Columna("producto", "Producto"),
                    Columna("inicial", "Inicial", "kg"),
                    Columna("entradas", "Entradas", "kg"),
                    Columna("salidas", "Salidas", "kg"),
                    Columna("t_entran", "Traslados que entran", "kg"),
                    Columna("t_salen", "Traslados que salen", "kg"),
                    Columna("mermas", "Mermas", "kg"),
                    Columna("ajustes", "Ajustes", "kg"),
                    Columna("final", "Final calculado", "kg"),
                    Columna("registrada", "Existencia registrada", "kg"),
                    Columna("cuadre", "Cuadre"),
                ],
                resumen_filas,
                totales if resumen_filas else {},
                nota=(
                    "Final = inicial + entradas - salidas + traslados que entran - traslados "
                    "que salen - mermas + ajustes. Cuadra si coincide con la existencia "
                    "registrada hoy."
                ),
            ),
            Seccion(
                "Totales por tipo de movimiento",
                [
                    Columna("clase", "Clase"),
                    Columna("ambito", "Ámbito"),
                    Columna("tipo", "Tipo de movimiento"),
                    Columna("n", "Movimientos", "entero"),
                    Columna("kg", "Kg", "kg"),
                ],
                tipos,
            ),
            Seccion(
                "Detalle de movimientos del periodo",
                [
                    Columna("fecha", "Fecha y hora", "fechahora"),
                    Columna("ambito", "Ámbito"),
                    Columna("ubicacion", "Ubicación"),
                    Columna("lote", "Lote"),
                    Columna("producto", "Producto"),
                    Columna("tipo", "Tipo"),
                    Columna("clase", "Clase"),
                    Columna("efecto", "Efecto (kg)", "kg"),
                    Columna("usuario", "Registró"),
                ],
                detalle,
                nota="El efecto es lo que el movimiento sumó o restó dentro del alcance.",
            ),
        ],
        nota=(
            "Clasificación: entradas = recepción, producción por transformación e inventario "
            "inicial; salidas = despacho mayorista, consumo por transformación y ventas; "
            "traslados = entre zonas, embultaje y a punto de venta; mermas = merma de "
            "embultaje y ajustes por pérdida o vencimiento; ajustes = sobrante, error de "
            "conteo (incluye reversos) u otro. "
            + (SIN_LOTE_EN_PDV if lote is not None and alcance.puntos else "")
        ).strip(),
    )


def _tipo_bodega(tipo, interno):
    etiqueta = TipoMovimiento(tipo).label
    return f"{etiqueta} (dentro del alcance)" if interno else etiqueta


def _registradas(alcance, producto, lote, con_pdv):
    """La existencia registrada hoy por producto dentro del alcance."""
    registradas = defaultdict(lambda: CERO)
    if alcance.bodega:
        existencias = Existencia.objects.filter(ubicacion_id__in=alcance.bodega)
        if producto is not None:
            existencias = existencias.filter(lote__producto=producto)
        if lote is not None:
            existencias = existencias.filter(lote=lote)
        for g in existencias.values("lote__producto").annotate(kg=Sum("cantidad")).order_by():
            registradas[g["lote__producto"]] += g["kg"]
    if con_pdv:
        existencias = ExistenciaPuntoVenta.objects.filter(ubicacion_id__in=alcance.puntos)
        if producto is not None:
            existencias = existencias.filter(producto=producto)
        for g in existencias.values("producto").annotate(kg=Sum("cantidad")).order_by():
            registradas[g["producto"]] += g["kg"]
    return registradas


def _detalle(alcance, producto, lote, con_pdv, inicio, fin):
    """Cada movimiento del periodo con su clase y su efecto dentro del alcance."""
    filas = []
    if alcance.bodega:
        movimientos = (
            _bodega(alcance, producto, lote)
            .filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
            .select_related("lote__producto", "ubicacion_origen", "ubicacion_destino", "usuario")
        )
        for m in movimientos:
            origen = m.ubicacion_origen.nombre if m.ubicacion_origen else ""
            destino = m.ubicacion_destino.nombre if m.ubicacion_destino else ""
            efecto = CERO if (m.entra and m.sale) else (m.cantidad if m.entra else -m.cantidad)
            filas.append(
                {
                    "fecha": m.fecha_hora,
                    "orden": (m.fecha_hora, 0, m.pk),
                    "ambito": "Bodega",
                    "ubicacion": " > ".join(u for u in (origen, destino) if u),
                    "lote": m.lote.codigo,
                    "producto": m.lote.producto.nombre,
                    "tipo": m.get_tipo_display(),
                    "clase": NOMBRES[clase_bodega(m.tipo, m.motivo_ajuste)],
                    "efecto": efecto,
                    "usuario": m.usuario.nombre_completo,
                }
            )
    if con_pdv:
        movimientos = (
            _pdv(alcance, producto)
            .filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
            .select_related("producto", "ubicacion", "usuario")
        )
        for m in movimientos:
            entra = m.sentido == SentidoMovimientoPdv.ENTRADA
            filas.append(
                {
                    "fecha": m.fecha_hora,
                    "orden": (m.fecha_hora, 1, m.pk),
                    "ambito": "Punto de venta",
                    "ubicacion": m.ubicacion.nombre,
                    "lote": "",
                    "producto": m.producto.nombre,
                    "tipo": m.get_tipo_display(),
                    "clase": NOMBRES[clase_pdv(m.tipo, m.motivo_ajuste)],
                    "efecto": m.cantidad if entra else -m.cantidad,
                    "usuario": m.usuario.nombre_completo,
                }
            )
    filas.sort(key=lambda f: f["orden"])
    return filas
