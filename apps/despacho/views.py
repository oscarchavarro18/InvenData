"""Pantallas del despacho mayorista y del traslado a punto de venta (M6).

Despacho: consultar es de todo perfil menos el administrador de punto de venta (RN-06);
despachar y registrar la entrega exige perfil de gerente o jefe de bodega (RF-02, RN-05).

Traslado: bodega lo envía (gerente o jefe de bodega); el administrador del PDV destino, o el
Gerente, lo acepta o lo rechaza. El administrador de PDV solo ve los traslados de su punto.
Las escrituras pasan por `apps/despacho/servicios.py`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import Evidencia
from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega
from apps.despacho.consultas import candidatos_traslado
from apps.despacho.forms import (
    DespachoForm,
    EntregaForm,
    LineaDespachoFormSet,
    LineaTrasladoFormSet,
    ObservacionForm,
    TrasladoForm,
    VerificacionForm,
)
from apps.despacho.models import DespachoMayorista, EstadoTraslado, TrasladoPdv
from apps.despacho.servicios import (
    CERO,
    ErrorDespacho,
    aceptar_traslado,
    agregar_observacion,
    crear_traslado,
    despachar_pedido,
    rechazar_traslado,
    registrar_entrega,
    ve_traslado,
)
from apps.embultaje.models import AlistamientoDetalle, EstadoPedido, Pedido
from apps.inventario.servicios import ErrorInventario
from apps.puntoventa.servicios import ErrorPuntoVenta

ERRORES_DE_NEGOCIO = (ErrorDespacho, ErrorInventario, ErrorPuntoVenta)
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


# --- Traslado a punto de venta (RF-38 a RF-45) -------------------------------


@login_required
def traslado_lista(request):
    """Bodega ve todos los traslados; el administrador de PDV, la bandeja de su punto (RF-39)."""
    traslados = TrasladoPdv.objects.select_related(
        "ubicacion_origen", "ubicacion_destino", "usuario_responsable"
    )
    if request.user.es_admin_pdv:
        traslados = traslados.filter(ubicacion_destino_id=request.user.ubicacion_id)
    elif not request.user.ve_bodega:
        raise PermissionDenied
    estado = request.GET.get("estado", "")
    if estado in EstadoTraslado.values:
        traslados = traslados.filter(estado=estado)
    pagina, consulta = paginar(request, traslados)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "estado": estado,
        "estados": EstadoTraslado.choices,
    }
    return render(request, "despacho/traslado_lista.html", contexto)


def _formulario_de_envio(request, anterior):
    """Arma el encabezado y las filas de lotes; con `anterior`, propone lo del rechazado."""
    enviado = request.method == "POST"
    datos = request.POST if enviado else None
    inicial = {}
    if anterior is not None:
        inicial = {
            "ubicacion_origen": anterior.ubicacion_origen_id,
            "ubicacion_destino": anterior.ubicacion_destino_id,
            "nombre_entrega": anterior.nombre_entrega,
        }
    # Al elegir el origen la página se recarga por GET con lo ya escrito.
    for campo in ("ubicacion_origen", "ubicacion_destino", "nombre_entrega"):
        if request.GET.get(campo):
            inicial[campo] = request.GET[campo]
    form = TrasladoForm(datos, initial=inicial)
    origen_id = (datos or request.GET).get("ubicacion_origen") or inicial.get("ubicacion_origen")
    origen = form.fields["ubicacion_origen"].queryset.filter(pk=origen_id).first()
    candidatos = candidatos_traslado(origen) if origen else []
    filas_iniciales = []
    if anterior is not None and not enviado:
        filas_iniciales = [
            {"candidato": str(d.lote_id), "cantidad": d.cantidad} for d in anterior.detalles.all()
        ]
    formset = LineaTrasladoFormSet(
        datos if origen else None,
        initial=filas_iniciales,
        form_kwargs={"candidatos": candidatos},
    )
    return form, formset, origen


@operador_de_bodega
def traslado_crear(request):
    """Envío a un PDV (RF-38). Con ?anterior=<id>, reenvío corregido de un rechazo (RF-44)."""
    anterior = None
    if request.GET.get("anterior", "").isdigit():
        anterior = get_object_or_404(
            TrasladoPdv, pk=request.GET["anterior"], estado=EstadoTraslado.RECHAZADO
        )
    form, formset, origen = _formulario_de_envio(request, anterior)
    if request.method == "POST" and origen and form.is_valid() and formset.is_valid():
        lineas = [
            {"lote": f.cleaned_data["lote"], "cantidad": f.cleaned_data["cantidad"]}
            for f in formset
            if f.cleaned_data.get("lote")
        ]
        try:
            traslado = crear_traslado(
                origen=form.cleaned_data["ubicacion_origen"],
                destino=form.cleaned_data["ubicacion_destino"],
                nombre_entrega=form.cleaned_data["nombre_entrega"],
                lineas=lineas,
                usuario=request.user,
                traslado_anterior=anterior,
                ip=ip_de(request),
            )
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Traslado {traslado.consecutivo} enviado a {traslado.ubicacion_destino.nombre}: "
                "ya aparece en su bandeja.",
            )
            return redirect("despacho:traslado_detalle", pk=traslado.pk)
    contexto = {"form": form, "formset": formset, "origen": origen, "anterior": anterior}
    return render(request, "despacho/traslado_form.html", contexto)


def _traslado_visible(request, pk):
    traslado = get_object_or_404(
        TrasladoPdv.objects.select_related(
            "ubicacion_origen",
            "ubicacion_destino",
            "usuario_responsable",
            "usuario_confirma",
            "traslado_anterior",
        ),
        pk=pk,
    )
    if not ve_traslado(request.user, traslado):
        raise PermissionDenied
    return traslado


@login_required
def traslado_detalle(request, pk, verificacion=None):
    traslado = _traslado_visible(request, pk)
    detalles = traslado.detalles.select_related("lote__producto")
    decide = traslado.estado == EstadoTraslado.ENVIADO and request.user.opera_punto_venta(
        traslado.ubicacion_destino
    )
    participa = request.user.puede_operar_bodega or request.user.opera_punto_venta(
        traslado.ubicacion_destino
    )
    contexto = {
        "traslado": traslado,
        "detalles": detalles,
        "observaciones": traslado.observaciones.select_related("usuario"),
        "reenvio": traslado.reenvios.first(),
        "verificacion": verificacion or (VerificacionForm(detalles=detalles) if decide else None),
        "observacion_form": ObservacionForm() if participa else None,
        "puede_reenviar": traslado.estado == EstadoTraslado.RECHAZADO
        and request.user.puede_operar_bodega
        and not traslado.reenvios.exists(),
    }
    return render(request, "despacho/traslado_detalle.html", contexto)


@login_required
@require_POST
def traslado_decidir(request, pk):
    """El PDV acepta o rechaza lo recibido, según el botón que pulse (RF-42, RF-43)."""
    traslado = _traslado_visible(request, pk)
    form = VerificacionForm(request.POST, detalles=traslado.detalles.select_related("lote"))
    if not form.is_valid():
        return traslado_detalle(request, pk, verificacion=form)
    aceptar = request.POST.get("accion") == "aceptar"
    try:
        if aceptar:
            aceptar_traslado(
                traslado=traslado,
                usuario=request.user,
                nombre_coincide=form.cleaned_data["nombre_coincide"],
                verificadas=form.pesos(),
                ip=ip_de(request),
            )
        else:
            rechazar_traslado(
                traslado=traslado,
                usuario=request.user,
                observacion=form.cleaned_data["observacion"],
                verificadas=form.pesos(),
                ip=ip_de(request),
            )
    except ERRORES_DE_NEGOCIO as error:
        form.add_error(None, str(error))
        return traslado_detalle(request, pk, verificacion=form)
    if aceptar:
        messages.success(
            request, f"Traslado {traslado.consecutivo} aceptado: el producto ya está en el punto."
        )
    else:
        messages.success(
            request, f"Traslado {traslado.consecutivo} rechazado. Bodega verá el motivo."
        )
    return redirect("despacho:traslado_detalle", pk=traslado.pk)


@login_required
@require_POST
def traslado_observar(request, pk):
    traslado = _traslado_visible(request, pk)
    form = ObservacionForm(request.POST)
    if form.is_valid():
        try:
            agregar_observacion(
                traslado=traslado,
                usuario=request.user,
                observacion=form.cleaned_data["observacion"],
                ip=ip_de(request),
            )
        except ERRORES_DE_NEGOCIO as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "Observación agregada.")
    else:
        messages.error(request, "Escriba la observación.")
    return redirect("despacho:traslado_detalle", pk=traslado.pk)
