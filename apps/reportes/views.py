"""Pantallas de reportes e indicadores de M9 (RF-54 a RF-66).

Cada reporte se ve en pantalla y se descarga en CSV o PDF con los mismos filtros
(`?formato=csv` o `?formato=pdf`), y lo que se exporta es exactamente lo que se ve. Solo se
lee: ningún reporte escribe en la base. El alcance sigue los perfiles (RF-02): la bodega no
la ve el Administrador de PDV (RN-06) y cada quien ve solo sus puntos de venta (RN-07).
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, ve_puntos_venta
from apps.puntoventa.consultas import puntos_visibles
from apps.reportes import consultas
from apps.reportes.exportar import respuesta_csv, respuesta_pdf
from apps.reportes.forms import (
    CorreccionesForm,
    ExistenciasBodegaForm,
    ExistenciasPdvForm,
    IndicadoresForm,
    InformeForm,
    MermasForm,
    PorVencerForm,
    TrazabilidadForm,
    VentasForm,
)
from apps.reportes.reporte import formatear

POR_PAGINA = 50
# En pantalla, cada sección de un reporte de varias partes muestra hasta este número de filas;
# el CSV y el PDF siempre llevan todas.
LIMITE_EN_PANTALLA = 300


def _ve_bodega(u):
    return u.ve_bodega


def _ve_algo(u):
    return u.ve_bodega or u.ve_algun_punto_venta


# El catálogo del índice: nombre de ruta, título, descripción y quién lo ve.
CATALOGO = (
    (
        "informe",
        "Informe general de inventario",
        "Inicial, entradas, salidas, traslados, mermas y final por periodo y alcance, con "
        "verificación de cuadre (RF-63 a RF-65).",
        _ve_algo,
    ),
    (
        "indicadores",
        "Indicadores de gestión",
        "Merma, rendimiento, tiempos, rechazos, FIFO, ventas y cobertura (RF-61).",
        _ve_algo,
    ),
    (
        "trazabilidad",
        "Trazabilidad de un lote",
        "Del documento del proveedor a su salida de bodega, con su balance (RF-54).",
        _ve_bodega,
    ),
    (
        "mermas",
        "Mermas",
        "Por etapa y acumulada por línea de recepción, hasta lo aprovechado (RF-55).",
        _ve_bodega,
    ),
    (
        "existencias_bodega",
        "Existencias de bodega",
        "Kg por ubicación y lote, con estado y días para vencer (RF-56).",
        _ve_bodega,
    ),
    (
        "existencias_pdv",
        "Existencias de punto de venta",
        "Kg por producto en cada punto, con su participación (RF-57).",
        lambda u: u.ve_algun_punto_venta,
    ),
    (
        "por_vencer",
        "Lotes vencidos y por vencer",
        "Qué vence primero, cuánto y dónde está (RF-58).",
        _ve_bodega,
    ),
    (
        "ventas",
        "Ventas",
        "Kg y número de ventas por punto, producto y canal en un periodo (RF-59).",
        lambda u: u.ve_algun_punto_venta,
    ),
    (
        "correcciones",
        "Correcciones y ajustes",
        "Ajustes y reversos del Gerente, con motivo y justificación (RF-60).",
        _ve_algo,
    ),
)


def _pares(tabla, fila):
    return list(zip(tabla.celdas(fila), tabla.columnas, strict=True))


def _seccion(tabla):
    """Una sección lista para la plantilla, recortada en pantalla si es muy larga."""
    totales = tabla.fila_de_totales()
    return {
        "titulo": tabla.titulo,
        "columnas": tabla.columnas,
        "filas": [_pares(tabla, f) for f in tabla.filas[:LIMITE_EN_PANTALLA]],
        "total_filas": len(tabla.filas),
        "recortada": len(tabla.filas) > LIMITE_EN_PANTALLA,
        "totales": list(zip(totales, tabla.columnas, strict=True)) if totales else None,
        "nota": tabla.nota,
    }


def _responder(request, reporte, form, titulo="", ayuda=""):
    """El reporte en pantalla o descargado, según `formato`. Sin reporte, solo el filtro."""
    formato = request.GET.get("formato", "")
    if reporte is not None and formato == "csv":
        return respuesta_csv(reporte)
    if reporte is not None and formato == "pdf":
        return respuesta_pdf(reporte, request.user)

    exportar = request.GET.copy()
    for clave in ("pagina", "formato"):
        exportar.pop(clave, None)
    contexto = {
        "reporte": reporte,
        "form": form,
        "exportar": exportar.urlencode(),
        "limite": LIMITE_EN_PANTALLA,
        "titulo": titulo,
        "ayuda": ayuda,
    }
    if reporte is not None:
        contexto["resumen"] = [(e, formatear(v, t)) for e, v, t in reporte.resumen]
        contexto["secciones"] = [_seccion(t) for t in reporte.secciones]
        if reporte.columnas:  # la tabla principal se pagina
            filas = [_pares(reporte, f) for f in reporte.filas]
            pagina, consulta = paginar(request, filas, por_pagina=POR_PAGINA)
            totales = reporte.fila_de_totales()
            contexto.update(
                pagina=pagina,
                consulta=consulta,
                totales_visibles=bool(pagina.paginator.count) and not pagina.has_next(),
                totales=list(zip(totales, reporte.columnas, strict=True)) if totales else None,
            )
    return render(request, "reportes/reporte.html", contexto)


def _puntos(usuario, elegido):
    """Los puntos del reporte: el elegido si se puede ver, o todos los visibles."""
    puntos = puntos_visibles(usuario)
    if elegido is not None and puntos.filter(pk=elegido.pk).exists():
        return puntos.filter(pk=elegido.pk)
    return puntos


@login_required
def indice(request):
    """Los reportes que el perfil de la persona puede consultar."""
    reportes = [
        {"ruta": f"reportes:{ruta}", "titulo": titulo, "descripcion": descripcion}
        for ruta, titulo, descripcion, ve in CATALOGO
        if ve(request.user)
    ]
    if not reportes:
        raise PermissionDenied
    return render(request, "reportes/indice.html", {"reportes": reportes})


@acceso_bodega
def existencias_bodega(request):
    """Existencias de bodega por ubicación y lote (RF-56, RF-63)."""
    form = ExistenciasBodegaForm(request.GET)
    reporte = consultas.existencias_bodega(**form.valores())
    return _responder(request, reporte, form)


@ve_puntos_venta
def existencias_pdv(request):
    """Existencias de los puntos de venta visibles por producto (RF-57)."""
    puntos = puntos_visibles(request.user)
    form = ExistenciasPdvForm(request.GET, puntos=puntos)
    valores = form.valores()
    reporte = consultas.existencias_pdv(
        puntos=_puntos(request.user, valores["ubicacion"]), producto=valores["producto"]
    )
    return _responder(request, reporte, form)


@acceso_bodega
def por_vencer(request):
    """Lotes vencidos y por vencer en bodega (RF-58)."""
    form = PorVencerForm(request.GET)
    reporte = consultas.por_vencer(**form.valores())
    return _responder(request, reporte, form)


@ve_puntos_venta
def ventas(request):
    """Ventas por punto, producto y canal en un periodo (RF-59)."""
    form = VentasForm(request.GET, puntos=puntos_visibles(request.user))
    valores = form.valores()
    reporte = consultas.ventas(puntos=_puntos(request.user, valores.pop("ubicacion")), **valores)
    return _responder(request, reporte, form)


@login_required
def correcciones(request):
    """Ajustes y reversos de bodega y PDV del alcance de la persona (RF-60)."""
    usuario = request.user
    puntos = puntos_visibles(usuario)
    ver_puntos = puntos.exists()
    if not (usuario.ve_bodega or ver_puntos):
        raise PermissionDenied
    form = CorreccionesForm(request.GET, ver_bodega=usuario.ve_bodega, ver_puntos=ver_puntos)
    reporte = consultas.correcciones(
        ver_bodega=usuario.ve_bodega, puntos=puntos if ver_puntos else None, **form.valores()
    )
    return _responder(request, reporte, form)


@acceso_bodega
def trazabilidad(request):
    """Trazabilidad de punta a punta de un lote (RF-54)."""
    form = TrazabilidadForm(request.GET)
    reporte = consultas.trazabilidad(form.cleaned_data["lote"]) if form.is_valid() else None
    return _responder(
        request,
        reporte,
        form,
        titulo="Trazabilidad de un lote",
        ayuda=(
            "Escriba el código del lote para ver de qué documento vino, cómo se pesó, si se "
            "transformó o embultó y en qué despacho o traslado salió de la bodega."
        ),
    )


@acceso_bodega
def mermas(request):
    """Mermas por etapa y acumuladas por línea de recepción (RF-55)."""
    form = MermasForm(request.GET)
    reporte = consultas.mermas(**form.valores())
    return _responder(request, reporte, form)


@login_required
def informe(request):
    """Informe general de inventario por periodo y alcance, con cuadre (RF-63 a RF-65)."""
    if not consultas.opciones_de_alcance(request.user):
        raise PermissionDenied
    form = InformeForm(request.GET, usuario=request.user)
    valores = form.valores()
    alcance = consultas.resolver_alcance(request.user, valores.pop("alcance"))
    reporte = consultas.informe_general(alcance=alcance, **valores)
    return _responder(request, reporte, form)


@login_required
def indicadores(request):
    """Indicadores de gestión del periodo, según lo que el perfil puede ver (RF-61)."""
    usuario = request.user
    puntos = puntos_visibles(usuario)
    if not (usuario.ve_bodega or puntos.exists()):
        raise PermissionDenied
    form = IndicadoresForm(request.GET)
    reporte = consultas.indicadores(
        ver_bodega=usuario.ve_bodega, puntos=list(puntos), **form.valores()
    )
    return _responder(request, reporte, form)
