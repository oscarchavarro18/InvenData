"""Pantallas del inventario de bodega (M3).

Consultar es de todo perfil menos el administrador de punto de venta, que nunca ve la bodega
(RN-06); trasladar entre zonas exige perfil de gerente o jefe de bodega (RF-02, RF-19).
"""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import acceso_bodega, operador_de_bodega
from apps.inventario.consultas import (
    DIAS_POR_VENCER,
    existencia_del_lote,
    historial_de_lote,
    kg_en_bodega,
    lotes_con_existencia,
    lotes_por_vencer,
    orden_de_origen,
)
from apps.inventario.forms import TrasladoForm
from apps.inventario.models import Existencia, Lote
from apps.inventario.servicios import ErrorInventario, trasladar_entre_zonas
from apps.maestros.models import Ubicacion


@acceso_bodega
def existencias(request):
    """Existencia actual por lote y ubicación, con búsqueda por producto, lote o ubicación."""
    filas = Existencia.objects.filter(cantidad__gt=0).select_related("lote__producto", "ubicacion")
    q = request.GET.get("q", "").strip()
    ubicacion = request.GET.get("ubicacion", "").strip()
    if q:
        filas = filas.filter(
            Q(lote__codigo__icontains=q)
            | Q(lote__producto__nombre__icontains=q)
            | Q(lote__producto__codigo__icontains=q)
        )
    if ubicacion.isdigit():
        filas = filas.filter(ubicacion_id=int(ubicacion))
    filas = filas.order_by("lote__fecha_vencimiento", "lote__codigo", "ubicacion__codigo")

    pagina, consulta = paginar(request, filas)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "q": q,
        "ubicacion": ubicacion,
        "ubicaciones": Ubicacion.objects.filter(activo=True),
        "hoy": timezone.localdate(),
        "kg_en_bodega": kg_en_bodega(),
        "lotes_con_existencia": lotes_con_existencia().count(),
        "n_por_vencer": len(lotes_por_vencer()),
        "dias_por_vencer": DIAS_POR_VENCER,
    }
    return render(request, "inventario/existencias.html", contexto)


@acceso_bodega
def lote_detalle(request, pk):
    """Historial de un lote: de dónde viene, dónde está y todo lo que le ha pasado (RF-22)."""
    lote = get_object_or_404(
        Lote.objects.select_related(
            "producto", "lote_origen", "documento_proveedor_linea__documento_proveedor"
        ),
        pk=pk,
    )
    existencias_lote = list(existencia_del_lote(lote))
    pagina, consulta = paginar(request, historial_de_lote(lote))
    contexto = {
        "lote": lote,
        "existencias": existencias_lote,
        "total": sum(e.cantidad for e in existencias_lote),
        "derivados": lote.derivados.select_related("producto"),
        "orden_origen": orden_de_origen(lote),
        "pagina": pagina,
        "consulta": consulta,
        "hoy": timezone.localdate(),
    }
    return render(request, "inventario/lote_detalle.html", contexto)


@operador_de_bodega
def trasladar(request, lote_id, ubicacion_id):
    """Traslado interno de un lote desde la zona donde está hacia otra de la bodega (RF-19)."""
    existencia = get_object_or_404(
        Existencia.objects.select_related("lote__producto", "ubicacion"),
        lote_id=lote_id,
        ubicacion_id=ubicacion_id,
        cantidad__gt=0,
    )
    form = TrasladoForm(
        request.POST if request.method == "POST" else None,
        origen=existencia.ubicacion,
        initial={"cantidad": existencia.cantidad},
    )
    if request.method == "POST" and form.is_valid():
        try:
            movimiento = trasladar_entre_zonas(
                lote=existencia.lote,
                origen=existencia.ubicacion,
                usuario=request.user,
                ip=ip_de(request),
                **form.cleaned_data,
            )
        except ErrorInventario as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                f"Se trasladaron {movimiento.cantidad} kg del lote {existencia.lote.codigo} "
                f"a {movimiento.ubicacion_destino.nombre}.",
            )
            return redirect("inventario:existencias")
    return render(
        request, "inventario/traslado_form.html", {"form": form, "existencia": existencia}
    )
