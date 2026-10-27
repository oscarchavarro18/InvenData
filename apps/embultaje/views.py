"""Pantallas de embultaje, pedidos y alistamiento (M5).

Consultar es de todo perfil menos el administrador de punto de venta, que nunca ve la bodega
(RN-06); registrar embultajes, cerrar lotes, crear pedidos y alistarlos exige perfil de
gerente o jefe de bodega (RF-02, RN-05); anular un pedido es solo del Gerente. Las escrituras
pasan por `apps/embultaje/servicios.py`.
"""

from django.contrib import messages
from django.db.models import Count, Prefetch, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega, solo_gerente
from apps.embultaje.consultas import CERO, candidatos_fifo, resumen_de_cierre
from apps.embultaje.forms import (
    AnulacionForm,
    AsignacionForm,
    LineaPedidoForm,
    PedidoForm,
    RegistroForm,
)
from apps.embultaje.models import (
    AlistamientoDetalle,
    DocumentoEmbultaje,
    EmbultajeRegistro,
    EstadoPedido,
    Pedido,
    PedidoLinea,
)
from apps.embultaje.servicios import (
    ErrorEmbultaje,
    agregar_linea,
    anular_pedido,
    asignar_lote,
    cerrar_lote,
    crear_pedido,
    marcar_alistado,
    quitar_alistamiento,
    quitar_linea,
    registrar_embultaje,
    sugerir_fifo,
)
from apps.inventario.models import EstadoLote, Existencia, Lote
from apps.inventario.servicios import ErrorInventario

ERRORES_DE_NEGOCIO = (ErrorEmbultaje, ErrorInventario)


@acceso_bodega
def documento_lista(request):
    documentos = (
        DocumentoEmbultaje.objects.select_related("usuario")
        .annotate(n_registros=Count("registros"), kg=Sum("registros__total_kilos"))
        .order_by("-fecha")  # con agrupación Django ignora el orden del modelo
    )
    pagina, consulta = paginar(request, documentos)
    return render(
        request, "embultaje/documento_lista.html", {"pagina": pagina, "consulta": consulta}
    )


@acceso_bodega
def documento_detalle(request, pk):
    documento = get_object_or_404(DocumentoEmbultaje.objects.select_related("usuario"), pk=pk)
    total = documento.registros.aggregate(total=Sum("total_kilos"))["total"]
    registros = (
        documento.registros.select_related(
            "lote__producto", "ubicacion_origen", "ubicacion_destino", "usuario"
        )
        .annotate(n_bultos=Count("bultos"))
        .order_by("fecha_hora", "id")  # con agrupación Django ignora el orden del modelo
    )
    contexto = {"documento": documento, "registros": registros, "total": total}
    return render(request, "embultaje/documento_detalle.html", contexto)


@operador_de_bodega
def registro_crear(request, lote_id, ubicacion_id):
    """Embulta una tanda del lote desde la zona donde está (RN-23, RN-26)."""
    existencia = get_object_or_404(
        Existencia.objects.select_related("lote__producto", "ubicacion"),
        lote_id=lote_id,
        ubicacion_id=ubicacion_id,
        cantidad__gt=0,
    )
    form = RegistroForm(
        request.POST if request.method == "POST" else None, origen=existencia.ubicacion
    )
    if request.method == "POST" and form.is_valid():
        try:
            registro = registrar_embultaje(
                lote=existencia.lote,
                ubicacion_origen=existencia.ubicacion,
                usuario=request.user,
                ip=ip_de(request),
                **form.cleaned_data,
            )
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            bultos = registro.bultos.count()
            detalle = f" en {bultos} bultos" if bultos else ""
            messages.success(
                request,
                f"Se embultaron {registro.total_kilos} kg del lote {existencia.lote.codigo}"
                f"{detalle}.",
            )
            return redirect("embultaje:documento_detalle", pk=registro.documento_embultaje_id)
    return render(request, "embultaje/registro_form.html", {"form": form, "existencia": existencia})


@acceso_bodega
def registro_detalle(request, pk):
    registro = get_object_or_404(
        EmbultajeRegistro.objects.select_related(
            "documento_embultaje", "lote__producto", "ubicacion_origen", "ubicacion_destino"
        ),
        pk=pk,
    )
    contexto = {"registro": registro, "bultos": registro.bultos.all()}
    return render(request, "embultaje/registro_detalle.html", contexto)


@operador_de_bodega
def lote_cerrar(request, lote_id):
    """Vista previa del cierre y, al confirmar, marca el lote EMBULTADO con su merma."""
    lote = get_object_or_404(Lote.objects.select_related("producto"), pk=lote_id)
    if lote.estado == EstadoLote.EMBULTADO:
        messages.info(request, f"El lote {lote.codigo} ya está cerrado como embultado.")
        return redirect("inventario:lote_detalle", pk=lote.pk)
    if request.method == "POST":
        try:
            lote = cerrar_lote(lote=lote, usuario=request.user, ip=ip_de(request))
        except ERRORES_DE_NEGOCIO as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                f"Lote {lote.codigo} cerrado: {lote.total_embultado_kg} kg embultados y "
                f"{lote.merma_vs_origen_kg} kg de merma de embultaje.",
            )
            return redirect("inventario:lote_detalle", pk=lote.pk)
    contexto = {"lote": lote, "resumen": resumen_de_cierre(lote)}
    return render(request, "embultaje/cierre_lote.html", contexto)


# --- Pedidos y alistamiento (RF-32 a RF-34) ----------------------------------


@acceso_bodega
def pedido_lista(request):
    pedidos = (
        Pedido.objects.select_related("cliente")
        .annotate(n_lineas=Count("lineas"))
        .order_by("-fecha", "-id")  # con agrupación Django ignora el orden del modelo
    )
    estado = request.GET.get("estado", "")
    if estado in EstadoPedido.values:
        pedidos = pedidos.filter(estado=estado)
    pagina, consulta = paginar(request, pedidos)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "estado": estado,
        "estados": EstadoPedido.choices,
    }
    return render(request, "embultaje/pedido_lista.html", contexto)


@operador_de_bodega
def pedido_crear(request):
    form = PedidoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            pedido = crear_pedido(usuario=request.user, ip=ip_de(request), **form.cleaned_data)
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"Pedido {pedido.consecutivo} creado. Agregue sus líneas.")
            return redirect("embultaje:pedido_detalle", pk=pedido.pk)
    return render(request, "embultaje/pedido_form.html", {"form": form})


def _filas_del_pedido(pedido, con_formularios):
    """Una fila por línea: lo asignado, lo que falta y, si se puede operar, el formulario."""
    alistamientos = AlistamientoDetalle.objects.select_related("lote", "ubicacion")
    lineas = pedido.lineas.select_related("producto").prefetch_related(
        Prefetch("alistamientos", queryset=alistamientos)
    )
    filas = []
    for linea in lineas:
        detalles = list(linea.alistamientos.all())
        asignado = sum((d.cantidad for d in detalles), CERO)
        fila = {
            "linea": linea,
            "detalles": detalles,
            "asignado": asignado,
            "pendiente": max(linea.cantidad_solicitada - asignado, CERO),
        }
        if con_formularios and fila["pendiente"] > CERO:
            candidatos = candidatos_fifo(linea.producto)
            fila["candidatos"] = candidatos
            if candidatos:
                fila["asignacion"] = AsignacionForm(
                    prefix=f"l{linea.pk}",
                    candidatos=candidatos,
                    initial={"cantidad": min(fila["pendiente"], candidatos[0].disponible)},
                )
        filas.append(fila)
    return filas


@acceso_bodega
def pedido_detalle(request, pk):
    pedido = get_object_or_404(
        Pedido.objects.select_related("cliente", "usuario_crea", "usuario_alista", "usuario_anula"),
        pk=pk,
    )
    editable = pedido.estado == EstadoPedido.CREADO and request.user.puede_operar_bodega
    contexto = {
        "pedido": pedido,
        "filas": _filas_del_pedido(pedido, con_formularios=editable),
        "editable": editable,
        "linea_form": LineaPedidoForm() if editable else None,
        "puede_anular": request.user.es_gerente
        and pedido.estado in (EstadoPedido.CREADO, EstadoPedido.ALISTADO),
    }
    if contexto["puede_anular"]:
        contexto["anulacion_form"] = AnulacionForm()
    return render(request, "embultaje/pedido_detalle.html", contexto)


def _volver(pedido_id, ancla=""):
    url = reverse("embultaje:pedido_detalle", args=[pedido_id])
    return redirect(f"{url}#{ancla}" if ancla else url)


def _errores_como_mensajes(request, form):
    for campo, errores in form.errors.items():
        etiqueta = form.fields[campo].label if campo in form.fields else ""
        for error in errores:
            messages.error(request, f"{etiqueta}: {error}" if etiqueta else error)


def _ejecutar(request, accion, exito):
    """Llama al servicio y avisa del resultado; los errores de negocio se muestran."""
    try:
        resultado = accion()
    except ERRORES_DE_NEGOCIO as error:
        messages.error(request, str(error))
        return None
    messages.success(request, exito(resultado) if callable(exito) else exito)
    return resultado


@operador_de_bodega
@require_POST
def linea_agregar(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    form = LineaPedidoForm(request.POST)
    if form.is_valid():
        _ejecutar(
            request,
            lambda: agregar_linea(
                pedido=pedido, usuario=request.user, ip=ip_de(request), **form.cleaned_data
            ),
            "Línea agregada.",
        )
    else:
        _errores_como_mensajes(request, form)
    return _volver(pedido.pk)


@operador_de_bodega
@require_POST
def linea_quitar(request, pk):
    linea = get_object_or_404(PedidoLinea, pk=pk)
    _ejecutar(
        request,
        lambda: quitar_linea(linea=linea, usuario=request.user, ip=ip_de(request)),
        "Línea quitada.",
    )
    return _volver(linea.pedido_id)


@operador_de_bodega
@require_POST
def linea_sugerir(request, pk):
    linea = get_object_or_404(PedidoLinea, pk=pk)
    _ejecutar(
        request,
        lambda: sugerir_fifo(linea=linea, usuario=request.user, ip=ip_de(request)),
        lambda detalles: f"Se asignaron {len(detalles)} lote(s) por orden de entrada (FIFO).",
    )
    return _volver(linea.pedido_id, f"linea-{linea.pk}")


@operador_de_bodega
@require_POST
def linea_asignar(request, pk):
    linea = get_object_or_404(PedidoLinea.objects.select_related("producto"), pk=pk)
    form = AsignacionForm(
        request.POST, prefix=f"l{linea.pk}", candidatos=candidatos_fifo(linea.producto)
    )
    if form.is_valid():
        candidato = form.cleaned_data["candidato"]
        _ejecutar(
            request,
            lambda: asignar_lote(
                linea=linea,
                lote=candidato.lote,
                ubicacion=candidato.ubicacion,
                cantidad=form.cleaned_data["cantidad"],
                justificacion=form.cleaned_data["justificacion"],
                usuario=request.user,
                ip=ip_de(request),
            ),
            f"Lote {candidato.lote.codigo} asignado.",
        )
    else:
        _errores_como_mensajes(request, form)
    return _volver(linea.pedido_id, f"linea-{linea.pk}")


@operador_de_bodega
@require_POST
def alistamiento_quitar(request, pk):
    detalle = get_object_or_404(AlistamientoDetalle.objects.select_related("pedido_linea"), pk=pk)
    _ejecutar(
        request,
        lambda: quitar_alistamiento(detalle=detalle, usuario=request.user, ip=ip_de(request)),
        "Lote quitado de la línea.",
    )
    return _volver(detalle.pedido_linea.pedido_id, f"linea-{detalle.pedido_linea_id}")


@operador_de_bodega
@require_POST
def pedido_alistar(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    _ejecutar(
        request,
        lambda: marcar_alistado(pedido=pedido, usuario=request.user, ip=ip_de(request)),
        f"Pedido {pedido.consecutivo} alistado: queda listo para despacho.",
    )
    return _volver(pedido.pk)


@solo_gerente
@require_POST
def pedido_anular(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    form = AnulacionForm(request.POST)
    if form.is_valid():
        _ejecutar(
            request,
            lambda: anular_pedido(
                pedido=pedido,
                usuario=request.user,
                observacion=form.cleaned_data["observacion"],
                ip=ip_de(request),
            ),
            f"Pedido {pedido.consecutivo} anulado. Sus lotes quedan libres.",
        )
    else:
        _errores_como_mensajes(request, form)
    return _volver(pedido.pk)
