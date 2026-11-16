"""Pantallas de transformación (M4).

Consultar es de todo perfil menos el administrador de punto de venta, que nunca ve la bodega
(RN-06); crear, corregir, eliminar y confirmar órdenes exige perfil de gerente o jefe de
bodega (RF-02, RN-05). Las escrituras pasan por `apps/transformacion/servicios.py`.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega
from apps.inventario.models import Existencia
from apps.inventario.servicios import ErrorInventario
from apps.transformacion.forms import ConfirmacionForm, DerivadoFormSet, OrdenForm
from apps.transformacion.models import EstadoOrden, OrdenTransformacion
from apps.transformacion.servicios import (
    CLAVE_TOLERANCIA,
    ErrorTransformacion,
    confirmar_orden,
    crear_orden,
    editar_orden,
    eliminar_orden,
    tolerancia_vigente,
)

ERRORES_DE_NEGOCIO = (ErrorTransformacion, ErrorInventario)


@acceso_bodega
def orden_lista(request):
    ordenes = OrdenTransformacion.objects.select_related(
        "lote_origen__producto", "ubicacion_origen", "usuario"
    )
    estado = request.GET.get("estado", "")
    if estado in EstadoOrden.values:
        ordenes = ordenes.filter(estado=estado)
    pagina, consulta = paginar(request, ordenes)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "estado": estado,
        "estados": EstadoOrden.choices,
    }
    return render(request, "transformacion/orden_lista.html", contexto)


@operador_de_bodega
def orden_crear(request, lote_id, ubicacion_id):
    """Nueva orden en borrador desde una existencia del inventario (RF-23)."""
    existencia = get_object_or_404(
        Existencia.objects.select_related("lote__producto", "ubicacion"),
        lote_id=lote_id,
        ubicacion_id=ubicacion_id,
        cantidad__gt=0,
    )
    form = OrdenForm(
        request.POST if request.method == "POST" else None,
        initial={"cantidad_consumida": existencia.cantidad},
    )
    if request.method == "POST" and form.is_valid():
        try:
            orden = crear_orden(
                lote=existencia.lote,
                ubicacion_origen=existencia.ubicacion,
                usuario=request.user,
                ip=ip_de(request),
                **form.cleaned_data,
            )
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Orden {orden.consecutivo} creada en borrador. Cuando termine el corte o el "
                "reempaque, registre los derivados y confírmela.",
            )
            return redirect("transformacion:orden_detalle", pk=orden.pk)
    return render(
        request, "transformacion/orden_form.html", {"form": form, "existencia": existencia}
    )


def _detalle(request, orden, *, formset=None, confirmacion=None, edicion=None):
    """Pinta el detalle; en borrador, con los formularios para operar si la persona puede."""
    contexto = {"orden": orden}
    if orden.estado == EstadoOrden.CONFIRMADA:
        contexto["derivados"] = orden.derivados.select_related(
            "producto", "lote_derivado", "ubicacion_destino"
        )
    elif request.user.puede_operar_bodega:
        try:
            tolerancia = tolerancia_vigente()
        except ErrorTransformacion as error:
            tolerancia = None
            messages.warning(request, str(error))
        if formset is None:
            formset = DerivadoFormSet(form_kwargs={"orden": orden})
        if confirmacion is None:
            confirmacion = ConfirmacionForm()
        if edicion is None:
            edicion = OrdenForm(initial={"cantidad_consumida": orden.cantidad_consumida})
        contexto.update(
            puede_operar=True,
            tolerancia=tolerancia,
            clave_tolerancia=CLAVE_TOLERANCIA,
            formset=formset,
            confirmacion=confirmacion,
            edicion=edicion,
        )
    return render(request, "transformacion/orden_detalle.html", contexto)


def _ya_confirmada(request, orden):
    """Si la orden dejó de estar en borrador (doble envío, otra persona), avisa y vuelve."""
    if orden.estado == EstadoOrden.BORRADOR:
        return None
    messages.error(request, f"La orden {orden.consecutivo} ya está confirmada: no se modifica.")
    return redirect("transformacion:orden_detalle", pk=orden.pk)


def _orden(pk):
    return get_object_or_404(
        OrdenTransformacion.objects.select_related(
            "lote_origen__producto", "ubicacion_origen", "usuario"
        ),
        pk=pk,
    )


@acceso_bodega
def orden_detalle(request, pk):
    return _detalle(request, _orden(pk))


@operador_de_bodega
@require_POST
def orden_editar(request, pk):
    orden = _orden(pk)
    if respuesta := _ya_confirmada(request, orden):
        return respuesta
    form = OrdenForm(request.POST)
    if form.is_valid():
        try:
            editar_orden(orden=orden, usuario=request.user, ip=ip_de(request), **form.cleaned_data)
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Cantidad a consumir actualizada.")
            return redirect("transformacion:orden_detalle", pk=orden.pk)
    return _detalle(request, orden, edicion=form)


@operador_de_bodega
@require_POST
def orden_eliminar(request, pk):
    orden = _orden(pk)
    if respuesta := _ya_confirmada(request, orden):
        return respuesta
    try:
        eliminar_orden(orden=orden, usuario=request.user, ip=ip_de(request))
    except ERRORES_DE_NEGOCIO as error:
        messages.error(request, str(error))
        return redirect("transformacion:orden_detalle", pk=orden.pk)
    messages.success(request, f"Orden {orden.consecutivo} eliminada.")
    return redirect("transformacion:orden_lista")


@operador_de_bodega
@require_POST
def orden_confirmar(request, pk):
    """Registra los derivados y confirma: aquí, y solo aquí, se mueve la existencia (RF-29)."""
    orden = _orden(pk)
    if respuesta := _ya_confirmada(request, orden):
        return respuesta
    formset = DerivadoFormSet(request.POST, form_kwargs={"orden": orden})
    confirmacion = ConfirmacionForm(request.POST)
    if formset.is_valid() and confirmacion.is_valid():
        derivados = [f.cleaned_data for f in formset.forms if f.has_changed()]
        try:
            confirmar_orden(
                orden=orden,
                derivados=derivados,
                usuario=request.user,
                observacion=confirmacion.cleaned_data["observacion"],
                ip=ip_de(request),
            )
        except ERRORES_DE_NEGOCIO as error:
            confirmacion.add_error(None, str(error))
        else:
            orden.refresh_from_db()
            messages.success(
                request,
                f"Orden {orden.consecutivo} confirmada: se generaron "
                f"{orden.derivados.count()} lotes derivados.",
            )
            return redirect("transformacion:orden_detalle", pk=orden.pk)
    return _detalle(request, orden, formset=formset, confirmacion=confirmacion)
