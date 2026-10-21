"""Pantallas de consulta del inventario (M3)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from apps.core.paginacion import paginar
from apps.inventario.consultas import (
    DIAS_POR_VENCER,
    kg_en_bodega,
    lotes_con_existencia,
    lotes_por_vencer,
)
from apps.inventario.models import Existencia
from apps.maestros.models import Ubicacion


@login_required
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
