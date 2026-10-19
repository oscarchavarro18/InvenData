"""Pantallas de recepción de producto (M2)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404, render

from apps.inventario.models import Lote
from apps.recepcion.models import DocumentoProveedor, EstadoDocumento, Recepcion
from apps.recepcion.servicios import CERO


@login_required
def documento_lista(request):
    documentos = DocumentoProveedor.objects.select_related("proveedor").annotate(
        n_lineas=Count("lineas")
    )
    return render(request, "recepcion/documento_lista.html", {"documentos": documentos})


def _filas_del_documento(documento):
    """Una fila por línea, con sus lotes y tandas y lo recibido contra lo declarado.

    Con el documento abierto, lo recibido y la diferencia se calculan en vivo; ya cerrado,
    se muestran los valores congelados al cierre (RF-15).
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
        filas.append(
            {
                "linea": linea,
                "lotes": detalle_lotes,
                "recibido": recibido,
                "diferencia": diferencia,
            }
        )
    return filas


@login_required
def documento_detalle(request, pk):
    documento = get_object_or_404(DocumentoProveedor.objects.select_related("proveedor"), pk=pk)
    contexto = {"documento": documento, "filas": _filas_del_documento(documento)}
    return render(request, "recepcion/documento_detalle.html", contexto)
