"""Pantallas del levantamiento de inventario inicial (M0).

Cuenta quien opera la ubicación (Jefe de bodega o Gerente en bodega; administrador del punto
o Gerente en un PDV); solo el Gerente aprueba (RN-03). Las escrituras pasan por
`apps/levantamiento/servicios.py`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.servicios import ip_de
from apps.core.permisos import solo_gerente
from apps.inventario.servicios import ErrorInventario
from apps.levantamiento.forms import LoteContadoForm, ProductoContadoForm
from apps.levantamiento.models import (
    EstadoLevantamiento,
    InventarioInicial,
    InventarioInicialDetalleLote,
    InventarioInicialDetalleProducto,
)
from apps.levantamiento.servicios import (
    ErrorLevantamiento,
    agregar_lote,
    agregar_producto,
    aprobar_levantamiento,
    crear_levantamiento,
    es_punto_venta,
    puede_registrar,
    quitar_linea,
    ve_levantamiento,
    ya_opera,
)
from apps.maestros.models import Ubicacion
from apps.puntoventa.servicios import ErrorPuntoVenta

ERRORES_DE_NEGOCIO = (ErrorLevantamiento, ErrorInventario, ErrorPuntoVenta)
DETALLES = {"lote": InventarioInicialDetalleLote, "producto": InventarioInicialDetalleProducto}


@login_required
def levantamiento_lista(request):
    """Los levantamientos que la persona puede ver y las ubicaciones que aún puede arrancar."""
    usuario = request.user
    if not (usuario.ve_bodega or usuario.ve_algun_punto_venta):
        raise PermissionDenied
    levantamientos = [
        lev
        for lev in InventarioInicial.objects.select_related("ubicacion", "usuario")
        if ve_levantamiento(usuario, lev.ubicacion)
    ]
    por_arrancar = [
        u
        for u in Ubicacion.objects.filter(activo=True, inventario_inicial__isnull=True).order_by(
            "codigo"
        )
        if puede_registrar(usuario, u) and not ya_opera(u)
    ]
    contexto = {"levantamientos": levantamientos, "por_arrancar": por_arrancar}
    return render(request, "levantamiento/levantamiento_lista.html", contexto)


@login_required
@require_POST
def levantamiento_crear(request, ubicacion_id):
    ubicacion = get_object_or_404(Ubicacion, pk=ubicacion_id)
    try:
        levantamiento = crear_levantamiento(
            ubicacion=ubicacion, usuario=request.user, ip=ip_de(request)
        )
    except ERRORES_DE_NEGOCIO as error:
        messages.error(request, str(error))
        return redirect("levantamiento:levantamiento_lista")
    messages.success(request, f"Levantamiento de {ubicacion.nombre} abierto: registre lo contado.")
    return redirect("levantamiento:levantamiento_detalle", pk=levantamiento.pk)


def _levantamiento_visible(request, pk):
    levantamiento = get_object_or_404(
        InventarioInicial.objects.select_related("ubicacion", "usuario", "usuario_aprueba"), pk=pk
    )
    if not ve_levantamiento(request.user, levantamiento.ubicacion):
        raise PermissionDenied
    return levantamiento


@login_required
def levantamiento_detalle(request, pk, form=None):
    levantamiento = _levantamiento_visible(request, pk)
    en_pdv = es_punto_venta(levantamiento.ubicacion)
    editable = levantamiento.estado == EstadoLevantamiento.REGISTRADO and puede_registrar(
        request.user, levantamiento.ubicacion
    )
    if editable and form is None:
        form = ProductoContadoForm() if en_pdv else LoteContadoForm()
    contexto = {
        "levantamiento": levantamiento,
        "en_pdv": en_pdv,
        "lotes": levantamiento.lotes.select_related("producto", "lote"),
        "productos": levantamiento.productos.select_related("producto"),
        "editable": editable,
        "form": form if editable else None,
        "puede_aprobar": request.user.es_gerente
        and levantamiento.estado == EstadoLevantamiento.REGISTRADO,
    }
    return render(request, "levantamiento/levantamiento_detalle.html", contexto)


@login_required
@require_POST
def linea_agregar(request, pk):
    levantamiento = _levantamiento_visible(request, pk)
    en_pdv = es_punto_venta(levantamiento.ubicacion)
    form = (ProductoContadoForm if en_pdv else LoteContadoForm)(request.POST)
    if not form.is_valid():
        return levantamiento_detalle(request, pk, form=form)
    servicio = agregar_producto if en_pdv else agregar_lote
    try:
        servicio(
            levantamiento=levantamiento,
            usuario=request.user,
            ip=ip_de(request),
            **form.cleaned_data,
        )
    except ERRORES_DE_NEGOCIO as error:
        form.add_error(None, str(error))
        return levantamiento_detalle(request, pk, form=form)
    messages.success(request, "Registrado en el levantamiento. Todavía no crea existencia.")
    return redirect("levantamiento:levantamiento_detalle", pk=pk)


@login_required
@require_POST
def linea_quitar(request, tipo, pk):
    if tipo not in DETALLES:
        raise PermissionDenied
    detalle = get_object_or_404(DETALLES[tipo], pk=pk)
    try:
        quitar_linea(detalle=detalle, usuario=request.user, ip=ip_de(request))
    except ERRORES_DE_NEGOCIO as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Fila quitada del levantamiento.")
    return redirect("levantamiento:levantamiento_detalle", pk=detalle.inventario_inicial_id)


@solo_gerente
@require_POST
def levantamiento_aprobar(request, pk):
    levantamiento = get_object_or_404(InventarioInicial, pk=pk)
    try:
        aprobar_levantamiento(levantamiento=levantamiento, usuario=request.user, ip=ip_de(request))
    except ERRORES_DE_NEGOCIO as error:
        messages.error(request, str(error))
    else:
        messages.success(
            request,
            "Levantamiento aprobado: ya es existencia real. Desde ahora esta ubicación se "
            "corrige con ajustes.",
        )
    return redirect("levantamiento:levantamiento_detalle", pk=pk)
