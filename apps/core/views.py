from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from apps.inventario.consultas import (
    DIAS_POR_VENCER,
    kg_en_bodega,
    lotes_con_existencia,
    lotes_por_vencer,
)
from apps.recepcion.models import DocumentoProveedor, EstadoDocumento


def salud(request):
    """Verificación de salud: responde 200 si la aplicación y la base de datos están vivas."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"estado": "ok", "base_de_datos": "ok"})
    except Exception:  # noqa: BLE001
        return JsonResponse({"estado": "error", "base_de_datos": "sin conexión"}, status=503)


@login_required
def inicio(request):
    """Tablero: indicadores del día, últimas recepciones y lotes próximos a vencer."""
    por_vencer = lotes_por_vencer()
    contexto = {
        "documentos_abiertos": DocumentoProveedor.objects.filter(
            estado=EstadoDocumento.ABIERTO
        ).count(),
        "kg_en_bodega": kg_en_bodega(),
        "lotes_con_existencia": lotes_con_existencia().count(),
        "n_por_vencer": len(por_vencer),
        "por_vencer": por_vencer[:5],
        "dias_por_vencer": DIAS_POR_VENCER,
        "recientes": DocumentoProveedor.objects.select_related("proveedor")[:5],
    }
    return render(request, "inicio.html", contexto)
