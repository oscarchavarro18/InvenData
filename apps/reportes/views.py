"""Pantallas de reportes de M9 (RF-56 a RF-60, RF-63, RF-66).

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
    PorVencerForm,
    VentasForm,
)
from apps.reportes.reporte import formatear

POR_PAGINA = 50

# El catálogo del índice: nombre de ruta, título, descripción y quién lo ve.
CATALOGO = (
    (
        "existencias_bodega",
        "Existencias de bodega",
        "Kg por ubicación y lote, con estado y días para vencer (RF-56).",
        lambda u: u.ve_bodega,
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
        lambda u: u.ve_bodega,
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
        lambda u: u.ve_bodega or u.ve_algun_punto_venta,
    ),
)


def _responder(request, reporte, form):
    """El reporte en pantalla o descargado, según `formato`."""
    formato = request.GET.get("formato", "")
    if formato == "csv":
        return respuesta_csv(reporte)
    if formato == "pdf":
        return respuesta_pdf(reporte, request.user)

    filas = [list(zip(reporte.celdas(f), reporte.columnas, strict=True)) for f in reporte.filas]
    pagina, consulta = paginar(request, filas, por_pagina=POR_PAGINA)
    totales = reporte.fila_de_totales()
    exportar = request.GET.copy()
    for clave in ("pagina", "formato"):
        exportar.pop(clave, None)
    contexto = {
        "reporte": reporte,
        "form": form,
        "pagina": pagina,
        "consulta": consulta,
        "exportar": exportar.urlencode(),
        "totales": list(zip(totales, reporte.columnas, strict=True)) if totales else None,
        "resumen": [(etiqueta, formatear(v, t)) for etiqueta, v, t in reporte.resumen],
    }
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
