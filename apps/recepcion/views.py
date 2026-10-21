"""Pantallas de recepción de producto (M2).

Leer es abierto a todo usuario con sesión; crear documentos, lotes y pesadas y cerrar el
documento exige perfil de gerente o jefe de bodega (RF-02).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.permisos import operador_de_recepcion
from apps.inventario.models import Lote
from apps.recepcion.forms import DocumentoForm, LineaForm, LoteForm, TandaForm
from apps.recepcion.models import (
    DocumentoProveedor,
    DocumentoProveedorLinea,
    EstadoDocumento,
    Recepcion,
)
from apps.recepcion.servicios import (
    CERO,
    RecepcionInvalida,
    agregar_linea,
    crear_documento,
    crear_lote_recepcion,
    eliminar_linea,
    eliminar_lote_sin_pesadas,
    registrar_pesada,
)


@login_required
def documento_lista(request):
    documentos = DocumentoProveedor.objects.select_related("proveedor").annotate(
        n_lineas=Count("lineas")
    )
    return render(request, "recepcion/documento_lista.html", {"documentos": documentos})


@operador_de_recepcion
def documento_crear(request):
    form = DocumentoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            documento = crear_documento(**form.cleaned_data)
        except RecepcionInvalida as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Documento creado. Agregue ahora sus líneas.")
            return redirect("recepcion:documento_detalle", pk=documento.pk)
    return render(request, "recepcion/documento_form.html", {"form": form})


def _filas_del_documento(documento, con_formularios=False):
    """Una fila por línea, con sus lotes y tandas y lo recibido contra lo declarado.

    Con el documento abierto, lo recibido y la diferencia se calculan en vivo; ya cerrado,
    se muestran los valores congelados al cierre (RF-15).
    Con `con_formularios`, cada línea trae su formulario de nuevo lote (el de pesada se dibuja
    a mano en la plantilla con las mismas listas para todos los lotes, así no consulta la base
    una vez por lote).
    """
    tandas = Recepcion.objects.select_related("tipo_embalaje", "ubicacion_destino")
    lotes = Lote.objects.order_by("codigo").prefetch_related(Prefetch("tandas", queryset=tandas))
    lineas = documento.lineas.select_related("producto").prefetch_related(
        Prefetch("lotes", queryset=lotes)
    )
    cerrado = documento.estado == EstadoDocumento.CERRADO

    filas = []
    for linea in lineas:
        detalle_lotes = []
        recibido = CERO
        for lote in linea.lotes.all():
            lista = list(lote.tandas.all())
            total = sum((t.peso_neto for t in lista), CERO)
            recibido += total
            detalle_lotes.append({"lote": lote, "tandas": lista, "total": total})
        if cerrado:
            recibido, diferencia = linea.cantidad_recibida, linea.diferencia_kg
        else:
            diferencia = linea.cantidad - recibido
        fila = {
            "linea": linea,
            "lotes": detalle_lotes,
            "recibido": recibido,
            "diferencia": diferencia,
        }
        if con_formularios:
            fila["lote_form"] = LoteForm(auto_id=f"id_%s_l{linea.pk}")
        filas.append(fila)
    return filas


@login_required
def documento_detalle(request, pk):
    documento = get_object_or_404(DocumentoProveedor.objects.select_related("proveedor"), pk=pk)
    abierto = documento.estado == EstadoDocumento.ABIERTO
    puede_operar = abierto and request.user.puede_operar_recepcion
    filas = _filas_del_documento(documento, con_formularios=puede_operar)
    contexto = {
        "documento": documento,
        "filas": filas,
        "puede_operar": puede_operar,
        "linea_form": LineaForm() if puede_operar else None,
    }
    if puede_operar:
        contexto.update(
            embalajes=TandaForm.base_fields["tipo_embalaje"].queryset,
            destinos=TandaForm.base_fields["ubicacion_destino"].queryset,
        )
        contexto["taras"] = {str(e.pk): str(e.peso_tara) for e in contexto["embalajes"]}
    return render(request, "recepcion/documento_detalle.html", contexto)


def _errores_como_mensajes(request, form):
    for campo, errores in form.errors.items():
        etiqueta = ""
        if campo in form.fields:
            etiqueta = form.fields[campo].label or campo.capitalize()
        for error in errores:
            messages.error(request, f"{etiqueta}: {error}" if etiqueta else error)


def _aplicar(request, form, accion, exito):
    """Ejecuta `accion(**datos)` si el formulario es válido y avisa del resultado."""
    if not form.is_valid():
        _errores_como_mensajes(request, form)
        return
    try:
        accion(**form.cleaned_data)
    except RecepcionInvalida as error:
        messages.error(request, str(error))
    else:
        messages.success(request, exito)


def _volver(documento_id, ancla=""):
    """Vuelve al detalle del documento, posicionado en la línea o el lote trabajado."""
    url = reverse("recepcion:documento_detalle", args=[documento_id])
    return redirect(f"{url}#{ancla}" if ancla else url)


@operador_de_recepcion
@require_POST
def linea_agregar(request, pk):
    documento = get_object_or_404(DocumentoProveedor, pk=pk)
    _aplicar(
        request,
        LineaForm(request.POST),
        lambda **datos: agregar_linea(documento=documento, **datos),
        "Línea agregada.",
    )
    return _volver(documento.pk)


@operador_de_recepcion
@require_POST
def linea_eliminar(request, pk):
    linea = get_object_or_404(DocumentoProveedorLinea, pk=pk)
    try:
        eliminar_linea(linea=linea)
    except RecepcionInvalida as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Línea eliminada.")
    return _volver(linea.documento_proveedor_id)


@operador_de_recepcion
@require_POST
def lote_crear(request, pk):
    linea = get_object_or_404(DocumentoProveedorLinea, pk=pk)
    _aplicar(
        request,
        LoteForm(request.POST),
        lambda **datos: crear_lote_recepcion(linea=linea, **datos),
        "Lote creado. Registre ahora sus pesadas.",
    )
    return _volver(linea.documento_proveedor_id, f"linea-{linea.pk}")


@operador_de_recepcion
@require_POST
def lote_eliminar(request, pk):
    lote = get_object_or_404(Lote.objects.select_related("documento_proveedor_linea"), pk=pk)
    linea = lote.documento_proveedor_linea
    try:
        eliminar_lote_sin_pesadas(lote=lote)
    except RecepcionInvalida as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Lote eliminado.")
    return _volver(linea.documento_proveedor_id, f"linea-{linea.pk}")


@operador_de_recepcion
@require_POST
def pesada_registrar(request, pk):
    lote = get_object_or_404(Lote.objects.select_related("documento_proveedor_linea"), pk=pk)
    if lote.documento_proveedor_linea_id is None:
        messages.error(request, "Solo se pesan lotes que vienen de una recepción.")
        return redirect("recepcion:documento_lista")
    _aplicar(
        request,
        TandaForm(request.POST),
        lambda **datos: registrar_pesada(lote=lote, usuario=request.user, **datos),
        f"Pesada registrada en el lote {lote.codigo}.",
    )
    return _volver(lote.documento_proveedor_linea.documento_proveedor_id, f"lote-{lote.pk}")
