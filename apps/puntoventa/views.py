"""Pantallas del punto de venta (M7).

El administrador de punto de venta solo ve y opera su propia ubicación; el Gerente puede
elegir cualquier PDV y vender en él; el perfil Consulta lee todos (RF-03, RN-06, RN-07). El
Jefe de bodega no opera los puntos de venta. Las escrituras pasan por
`apps/puntoventa/servicios.py`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.puntoventa.consultas import (
    historial_pdv,
    punto_elegido,
    puntos_visibles,
    totales_del_rango,
)
from apps.puntoventa.forms import (
    HistorialForm,
    LineaVentaFormSet,
    VentaConsumidorForm,
    VentaRestauranteForm,
)
from apps.puntoventa.models import (
    ExistenciaPuntoVenta,
    VentaConsumidorFinal,
    VentaRestauranteRemision,
)
from apps.puntoventa.servicios import (
    ErrorPuntoVenta,
    registrar_venta_consumidor,
    registrar_venta_restaurante,
)

# Los dos canales de venta (RN-33): su modelo, su formulario y cómo se llaman en pantalla.
CANALES = {
    "consumidor": {
        "modelo": VentaConsumidorFinal,
        "formulario": VentaConsumidorForm,
        "titulo": "Consumidor final",
    },
    "restaurante": {
        "modelo": VentaRestauranteRemision,
        "formulario": VentaRestauranteForm,
        "titulo": "Restaurante (remisión)",
    },
}


def _canal(tipo):
    if tipo not in CANALES:
        raise Http404
    return CANALES[tipo]


def _punto_visible(request, valor):
    """El PDV que pide la persona, dentro de su alcance; 403 si no ve ninguno."""
    if not request.user.ve_algun_punto_venta:
        raise PermissionDenied
    return punto_elegido(request.user, valor)


@login_required
def existencias(request):
    """Cuánto hay de cada producto en un punto de venta, en tiempo real (RF-48)."""
    punto = _punto_visible(request, request.GET.get("ubicacion", ""))
    filas = ExistenciaPuntoVenta.objects.none()
    if punto is not None:
        filas = (
            ExistenciaPuntoVenta.objects.filter(ubicacion=punto, cantidad__gt=0)
            .select_related("producto")
            .order_by("producto__nombre")
        )
    pagina, consulta = paginar(request, filas)
    contexto = {
        "punto": punto,
        "puntos": puntos_visibles(request.user),
        "pagina": pagina,
        "consulta": consulta,
    }
    return render(request, "puntoventa/existencias.html", contexto)


@login_required
def venta_lista(request):
    punto = _punto_visible(request, request.GET.get("ubicacion", ""))
    tipo = request.GET.get("tipo", "consumidor")
    canal = _canal(tipo)
    ventas = canal["modelo"].objects.none()
    if punto is not None:
        ventas = (
            canal["modelo"]
            .objects.filter(ubicacion=punto)
            .select_related("usuario", *(["cliente"] if tipo == "restaurante" else []))
            .annotate(n_productos=Count("lineas"), kg=Sum("lineas__cantidad"))
            .order_by("-fecha", "-id")  # con agrupación Django ignora el orden del modelo
        )
    pagina, consulta = paginar(request, ventas)
    contexto = {
        "punto": punto,
        "puntos": puntos_visibles(request.user),
        "tipo": tipo,
        "canales": CANALES,
        "pagina": pagina,
        "consulta": consulta,
        "puede_vender": punto is not None and request.user.opera_punto_venta(punto),
    }
    return render(request, "puntoventa/venta_lista.html", contexto)


@login_required
def venta_nueva(request, tipo):
    """Registra una venta en un solo paso: se descuenta de inmediato (RF-46, RF-47, RN-31)."""
    canal = _canal(tipo)
    enviado = request.method == "POST"
    punto = _punto_visible(request, (request.POST if enviado else request.GET).get("ubicacion"))
    if punto is None or not request.user.opera_punto_venta(punto):
        raise PermissionDenied
    disponibles = list(
        ExistenciaPuntoVenta.objects.filter(ubicacion=punto, cantidad__gt=0)
        .select_related("producto")
        .order_by("producto__nombre")
    )
    form = canal["formulario"](request.POST if enviado else None, request.FILES or None)
    formset = LineaVentaFormSet(
        request.POST if enviado else None, form_kwargs={"disponibles": disponibles}
    )
    if enviado and form.is_valid() and formset.is_valid():
        lineas = [
            {"producto": f.cleaned_data["producto"], "cantidad": f.cleaned_data["cantidad"]}
            for f in formset
            if f.cleaned_data.get("producto")
        ]
        try:
            if tipo == "consumidor":
                venta = registrar_venta_consumidor(
                    ubicacion=punto,
                    numero_factura_siigo=form.cleaned_data["numero_factura_siigo"],
                    lineas=lineas,
                    usuario=request.user,
                    ip=ip_de(request),
                )
            else:
                venta = registrar_venta_restaurante(
                    ubicacion=punto,
                    cliente=form.cleaned_data["cliente"],
                    lineas=lineas,
                    usuario=request.user,
                    autoriza_datos=form.cleaned_data["autoriza_datos"],
                    evidencia=form.cleaned_data["evidencia"],
                    ip=ip_de(request),
                )
        except ErrorPuntoVenta as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"{venta} registrada: la existencia ya se descontó.")
            return redirect("puntoventa:venta_detalle", tipo=tipo, pk=venta.pk)
    contexto = {
        "punto": punto,
        "puntos": [p for p in puntos_visibles(request.user) if request.user.opera_punto_venta(p)],
        "tipo": tipo,
        "canal": canal,
        "form": form,
        "formset": formset,
        "disponibles": disponibles,
    }
    return render(request, "puntoventa/venta_form.html", contexto)


@login_required
def venta_detalle(request, tipo, pk):
    canal = _canal(tipo)
    venta = get_object_or_404(canal["modelo"].objects.select_related("ubicacion", "usuario"), pk=pk)
    if not request.user.ve_punto_venta(venta.ubicacion):
        raise PermissionDenied
    lineas = venta.lineas.select_related("producto")
    contexto = {
        "venta": venta,
        "tipo": tipo,
        "canal": canal,
        "lineas": lineas,
        "total": sum((linea.cantidad for linea in lineas), 0),
    }
    return render(request, "puntoventa/venta_detalle.html", contexto)


@login_required
def historial(request):
    """Entradas por traslado y salidas por venta de un PDV en un rango de fechas (RF-49)."""
    punto = _punto_visible(request, request.GET.get("ubicacion", ""))
    form = HistorialForm(request.GET)
    desde, hasta, producto = form.rango()
    movimientos = historial_pdv(punto, desde, hasta, producto) if punto else []
    entradas, ventas = totales_del_rango(punto, desde, hasta, producto) if punto else (0, 0)
    pagina, consulta = paginar(request, movimientos)
    contexto = {
        "punto": punto,
        "puntos": puntos_visibles(request.user),
        "form": form,
        "pagina": pagina,
        "consulta": consulta,
        "entradas": entradas,
        "ventas": ventas,
    }
    return render(request, "puntoventa/historial.html", contexto)
