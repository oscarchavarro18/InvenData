"""Pantallas del conteo físico y de los ajustes y reversos de gerencia (M8).

Contar lo hace quien opera la ubicación: el Jefe de bodega o el Gerente en bodega, y el
administrador del punto o el Gerente en un PDV. Ajustar y reversar es solo del Gerente
(RN-32, RN-34). Las escrituras pasan por `apps/conteo/servicios.py`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.auditoria.servicios import ip_de
from apps.conteo.consultas import comparacion, conteos_visibles
from apps.conteo.forms import (
    AjusteForm,
    AjustePdvForm,
    ConteoForm,
    LineaConteoFormSet,
    ReversoForm,
)
from apps.conteo.models import ConteoFisico
from apps.conteo.servicios import (
    ErrorConteo,
    ajustar_bodega,
    ajustar_pdv,
    puede_contar,
    registrar_conteo,
    reversar_bodega,
    reversar_pdv,
    ve_conteo,
)
from apps.core.paginacion import paginar
from apps.core.permisos import solo_gerente
from apps.inventario.models import Existencia, Movimiento
from apps.inventario.servicios import ErrorInventario
from apps.maestros.models import Ubicacion
from apps.puntoventa.consultas import punto_elegido
from apps.puntoventa.models import MovimientoPuntoVenta
from apps.puntoventa.servicios import ErrorPuntoVenta

ERRORES_DE_NEGOCIO = (ErrorConteo, ErrorInventario, ErrorPuntoVenta)


# --- Conteo físico (RF-50 a RF-52) -------------------------------------------


@login_required
def conteo_lista(request):
    if not (request.user.ve_bodega or request.user.ve_algun_punto_venta):
        raise PermissionDenied
    conteos = conteos_visibles(request.user)
    pagina, consulta = paginar(request, conteos)
    puede_registrar = request.user.puede_operar_bodega or request.user.es_admin_pdv
    contexto = {"pagina": pagina, "consulta": consulta, "puede_registrar": puede_registrar}
    return render(request, "conteo/conteo_lista.html", contexto)


@login_required
def conteo_nuevo(request):
    ubicaciones = [
        u
        for u in Ubicacion.objects.filter(activo=True).order_by("codigo")
        if puede_contar(request.user, u)
    ]
    if not ubicaciones:
        raise PermissionDenied
    queryset = Ubicacion.objects.filter(pk__in=[u.pk for u in ubicaciones]).order_by("codigo")
    enviado = request.method == "POST"
    form = ConteoForm(request.POST if enviado else None, ubicaciones=queryset)
    formset = LineaConteoFormSet(request.POST if enviado else None)
    if enviado and form.is_valid() and formset.is_valid():
        lineas = [
            {
                "producto": f.cleaned_data["producto"],
                "cantidad_bultos": f.cleaned_data["cantidad_bultos"],
            }
            for f in formset
            if f.cleaned_data.get("producto")
        ]
        try:
            conteo = registrar_conteo(
                ubicacion=form.cleaned_data["ubicacion"],
                fecha=form.cleaned_data["fecha"],
                lineas=lineas,
                usuario=request.user,
                ip=ip_de(request),
            )
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Conteo registrado. No modifica la existencia del sistema.")
            return redirect("conteo:conteo_detalle", pk=conteo.pk)
    return render(request, "conteo/conteo_form.html", {"form": form, "formset": formset})


@login_required
def conteo_detalle(request, pk):
    conteo = get_object_or_404(ConteoFisico.objects.select_related("ubicacion", "usuario"), pk=pk)
    if not ve_conteo(request.user, conteo.ubicacion):
        raise PermissionDenied
    contexto = {"conteo": conteo, "filas": comparacion(conteo)}
    return render(request, "conteo/conteo_detalle.html", contexto)


# --- Ajustes y reversos del Gerente (RF-09, RF-53) ---------------------------


def _formulario_de_ajuste(request, form, ejecutar, volver, contexto):
    """Valida, ejecuta el servicio y vuelve; si hay un error de negocio lo muestra."""
    if request.method == "POST" and form.is_valid():
        try:
            ejecutar(form.cleaned_data)
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Ajuste registrado con su justificación.")
            return redirect(volver)
    return render(request, "conteo/ajuste_form.html", {**contexto, "form": form, "volver": volver})


@solo_gerente
def ajuste_bodega(request, lote_id, ubicacion_id):
    existencia = get_object_or_404(
        Existencia.objects.select_related("lote__producto", "ubicacion"),
        lote_id=lote_id,
        ubicacion_id=ubicacion_id,
    )
    form = AjusteForm(request.POST if request.method == "POST" else None)

    def ejecutar(datos):
        ajustar_bodega(
            lote=existencia.lote,
            ubicacion=existencia.ubicacion,
            usuario=request.user,
            ip=ip_de(request),
            **datos,
        )

    volver = reverse("inventario:lote_detalle", args=[lote_id])
    contexto = {
        "titulo": f"Lote {existencia.lote.codigo} en {existencia.ubicacion.nombre}",
        "actual": existencia.cantidad,
    }
    return _formulario_de_ajuste(request, form, ejecutar, volver, contexto)


@solo_gerente
def ajuste_pdv(request):
    punto = punto_elegido(request.user, request.GET.get("ubicacion", ""))
    if punto is None:
        raise PermissionDenied
    inicial = {}
    if request.GET.get("producto", "").isdigit():
        inicial["producto"] = request.GET["producto"]
    form = AjustePdvForm(request.POST if request.method == "POST" else None, initial=inicial)

    def ejecutar(datos):
        ajustar_pdv(ubicacion=punto, usuario=request.user, ip=ip_de(request), **datos)

    volver = f"{reverse('puntoventa:existencias')}?ubicacion={punto.pk}"
    contexto = {"titulo": punto.nombre, "actual": None}
    return _formulario_de_ajuste(request, form, ejecutar, volver, contexto)


def _formulario_de_reverso(request, ejecutar, volver, movimiento):
    form = ReversoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            ejecutar(form.cleaned_data["observacion"])
        except ERRORES_DE_NEGOCIO as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Movimiento reversado. El original se conserva.")
            return redirect(volver)
    contexto = {"form": form, "movimiento": movimiento, "volver": volver}
    return render(request, "conteo/reverso_form.html", contexto)


@solo_gerente
def reverso_bodega(request, movimiento_id):
    movimiento = get_object_or_404(
        Movimiento.objects.select_related("lote", "ubicacion_origen", "ubicacion_destino"),
        pk=movimiento_id,
    )

    def ejecutar(observacion):
        reversar_bodega(
            movimiento=movimiento, usuario=request.user, observacion=observacion, ip=ip_de(request)
        )

    volver = reverse("inventario:lote_detalle", args=[movimiento.lote_id])
    return _formulario_de_reverso(request, ejecutar, volver, movimiento)


@solo_gerente
def reverso_pdv(request, movimiento_id):
    movimiento = get_object_or_404(
        MovimientoPuntoVenta.objects.select_related("producto", "ubicacion"), pk=movimiento_id
    )

    def ejecutar(observacion):
        reversar_pdv(
            movimiento=movimiento, usuario=request.user, observacion=observacion, ip=ip_de(request)
        )

    volver = f"{reverse('puntoventa:historial')}?ubicacion={movimiento.ubicacion_id}"
    return _formulario_de_reverso(request, ejecutar, volver, movimiento)
