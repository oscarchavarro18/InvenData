"""Pantallas del despacho mayorista (M6).

Consultar es de todo perfil menos el administrador de punto de venta, que nunca ve la bodega
(RN-06); despachar y registrar la entrega exige perfil de gerente o jefe de bodega (RF-02,
RN-05). Las escrituras pasan por `apps/despacho/servicios.py`.
"""

from django.contrib import messages
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import Evidencia
from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega
from apps.despacho.forms import DespachoForm, EntregaForm, LineaDespachoFormSet
from apps.despacho.models import DespachoMayorista
from apps.despacho.servicios import CERO, ErrorDespacho, despachar_pedido, registrar_entrega
from apps.embultaje.models import AlistamientoDetalle, EstadoPedido, Pedido
from apps.inventario.servicios import ErrorInventario

ERRORES_DE_NEGOCIO = (ErrorDespacho, ErrorInventario)
ENTIDAD = DespachoMayorista._meta.db_table


@acceso_bodega
def despacho_lista(request):
    despachos = DespachoMayorista.objects.select_related("pedido__cliente", "usuario_despacha")
    pagina, consulta = paginar(request, despachos)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "por_despachar": Pedido.objects.filter(estado=EstadoPedido.ALISTADO).select_related(
            "cliente"
        ),
    }
    return render(request, "despacho/despacho_lista.html", contexto)


@operador_de_bodega
def despacho_crear(request, pedido_id):
    """Despacha un pedido alistado: cada lote planeado con el peso que de verdad se cargó."""
    pedido = get_object_or_404(Pedido.objects.select_related("cliente"), pk=pedido_id)
    if pedido.estado != EstadoPedido.ALISTADO:
        messages.error(request, f"El pedido {pedido.consecutivo} no está alistado para despacho.")
        return redirect("embultaje:pedido_detalle", pk=pedido.pk)
    alistamientos = list(
        AlistamientoDetalle.objects.filter(pedido_linea__pedido=pedido)
        .select_related("lote__producto", "ubicacion")
        .order_by("pk")
    )
    enviado = request.method == "POST"
    form = DespachoForm(request.POST if enviado else None)
    formset = LineaDespachoFormSet(
        request.POST if enviado else None,
        initial=[{"alistamiento": a.pk, "cantidad": a.cantidad} for a in alistamientos],
    )
    if enviado and form.is_valid() and formset.is_valid():
        por_id = {a.pk: a for a in alistamientos}
        lineas = [
            {**f.cleaned_data, "alistamiento": por_id.get(f.cleaned_data["alistamiento"])}
            for f in formset
        ]
        if any(linea["alistamiento"] is None for linea in lineas):
            form.add_error(None, "Las líneas no corresponden al alistamiento del pedido.")
        else:
            try:
                despacho = despachar_pedido(
                    pedido=pedido,
                    usuario=request.user,
                    lineas=lineas,
                    ip=ip_de(request),
                    **form.cleaned_data,
                )
            except ERRORES_DE_NEGOCIO as error:
                form.add_error(None, str(error))
            else:
                messages.success(
                    request,
                    f"Pedido {pedido.consecutivo} despachado: la existencia ya se descontó.",
                )
                return redirect("despacho:despacho_detalle", pk=despacho.pk)
    contexto = {
        "pedido": pedido,
        "form": form,
        "formset": formset,
        "filas": list(zip(formset.forms, alistamientos, strict=False)),
    }
    return render(request, "despacho/despacho_form.html", contexto)


def _trazos_svg(firma):
    """Convierte la firma guardada (trazos de puntos 0-1000) en caminos SVG para mostrarla."""
    caminos = []
    for trazo in firma or []:
        puntos = [f"{x:.0f},{y:.0f}" for x, y in trazo]
        caminos.append("M" + " L".join(puntos))
    return caminos


@acceso_bodega
def despacho_detalle(request, pk):
    despacho = get_object_or_404(
        DespachoMayorista.objects.select_related("pedido__cliente", "usuario_despacha"), pk=pk
    )
    detalles = despacho.detalles.select_related(
        "alistamiento_detalle__lote__producto", "alistamiento_detalle__ubicacion"
    )
    sin_entrega = despacho.fecha_hora_recepcion is None
    contexto = {
        "despacho": despacho,
        "detalles": detalles,
        "total": sum((d.cantidad for d in detalles), CERO),
        "evidencias": Evidencia.objects.filter(entidad=ENTIDAD, registro_id=despacho.pk),
        "trazos": _trazos_svg(despacho.firma_recibe_digital),
        "entrega_form": EntregaForm() if sin_entrega and request.user.puede_operar_bodega else None,
    }
    return render(request, "despacho/despacho_detalle.html", contexto)


@operador_de_bodega
@require_POST
def entrega_registrar(request, pk):
    despacho = get_object_or_404(DespachoMayorista, pk=pk)
    form = EntregaForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            registrar_entrega(
                despacho=despacho,
                usuario=request.user,
                nombre_recibe=form.cleaned_data["nombre_recibe"],
                firma=form.cleaned_data["firma"],
                archivo=form.cleaned_data["archivo"],
                ip=ip_de(request),
            )
        except ERRORES_DE_NEGOCIO as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Constancia de entrega registrada.")
    else:
        for errores in form.errors.values():
            for error in errores:
                messages.error(request, error)
    return redirect("despacho:despacho_detalle", pk=despacho.pk)


@acceso_bodega
def evidencia_ver(request, pk, evidencia_pk):
    """Muestra la foto del documento firmado; solo a quien puede ver la bodega."""
    evidencia = get_object_or_404(Evidencia, pk=evidencia_pk, entidad=ENTIDAD, registro_id=pk)
    return FileResponse(evidencia.archivo.open("rb"), content_type=evidencia.tipo_mime)
