"""Pantallas de embultaje (M5).

Consultar es de todo perfil menos el administrador de punto de venta, que nunca ve la bodega
(RN-06); registrar embultajes y cerrar lotes exige perfil de gerente o jefe de bodega
(RF-02, RN-05). Las escrituras pasan por `apps/embultaje/servicios.py`.
"""

from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega
from apps.embultaje.consultas import resumen_de_cierre
from apps.embultaje.forms import RegistroForm
from apps.embultaje.models import DocumentoEmbultaje, EmbultajeRegistro
from apps.embultaje.servicios import ErrorEmbultaje, cerrar_lote, registrar_embultaje
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
