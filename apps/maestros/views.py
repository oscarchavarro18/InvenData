"""Pantallas de maestros: productos y consulta de la configuración (M1)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, ip_de, registrar
from apps.core.paginacion import paginar
from apps.core.permisos import solo_gerente
from apps.maestros.forms import EmbalajeForm, ProductoForm
from apps.maestros.models import Parametro, Producto, TipoEmbalaje, Ubicacion


@login_required
def producto_lista(request):
    productos = (
        Producto.objects.select_related("categoria")
        .annotate(existencia=Sum("lotes__existencias__cantidad"))
        .order_by("codigo")  # con agrupación Django ignora el orden del modelo
    )
    q = request.GET.get("q", "").strip()
    if q:
        productos = productos.filter(
            Q(nombre__icontains=q) | Q(codigo__icontains=q) | Q(categoria__nombre__icontains=q)
        )
    pagina, consulta = paginar(request, productos)
    return render(
        request,
        "maestros/producto_lista.html",
        {"pagina": pagina, "consulta": consulta, "q": q},
    )


@solo_gerente  # los catálogos los administra la gerencia (RF-04)
def producto_crear(request):
    form = ProductoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            producto = form.save()
            producto.refresh_from_db()  # lo que quedó guardado (código en mayúsculas, decimales)
            registrar(
                usuario=request.user,
                entidad=producto._meta.db_table,
                registro_id=producto.pk,
                accion=AccionAuditoria.CREAR,
                valor_nuevo=instantanea(producto),
                ip=ip_de(request),
            )
        messages.success(request, f"Producto «{producto.nombre}» creado.")
        return redirect("maestros:producto_lista")
    return render(request, "maestros/producto_form.html", {"form": form})


@login_required
def configuracion(request):
    """Consulta de los catálogos de la operación. La edición se hace desde el panel de gestión."""
    contexto = {
        "ubicaciones": Ubicacion.objects.all(),
        "embalajes": TipoEmbalaje.objects.order_by("nombre"),
        "parametros": Parametro.objects.order_by("clave"),
    }
    return render(request, "maestros/configuracion.html", contexto)


def _registrar(request, objeto, accion, anterior=None):
    """Deja en auditoría lo que quedó guardado de un maestro (RF-10); va en la misma transacción."""
    objeto.refresh_from_db()
    registrar(
        usuario=request.user,
        entidad=objeto._meta.db_table,
        registro_id=objeto.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=instantanea(objeto),
        ip=ip_de(request),
    )


@solo_gerente
def embalaje_crear(request):
    form = EmbalajeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            embalaje = form.save()
            _registrar(request, embalaje, AccionAuditoria.CREAR)
        messages.success(request, f"Tipo de embalaje «{embalaje.nombre}» creado.")
        return redirect("maestros:configuracion")
    return render(request, "maestros/embalaje_form.html", {"form": form, "embalaje": None})


@solo_gerente
def embalaje_editar(request, pk):
    """Cambiar la tara solo afecta las pesadas nuevas: las ya registradas conservan su peso neto."""
    embalaje = get_object_or_404(TipoEmbalaje, pk=pk)
    form = EmbalajeForm(request.POST if request.method == "POST" else None, instance=embalaje)
    if request.method == "POST":
        anterior = instantanea(embalaje)
        if form.is_valid():
            with transaction.atomic():
                form.save()
                _registrar(request, embalaje, AccionAuditoria.MODIFICAR, anterior=anterior)
            messages.success(request, f"Tipo de embalaje «{embalaje.nombre}» actualizado.")
            return redirect("maestros:configuracion")
    return render(request, "maestros/embalaje_form.html", {"form": form, "embalaje": embalaje})


@solo_gerente
@require_POST
def embalaje_estado(request, pk):
    """Activa o desactiva un tipo: no se borra, porque las pesadas antiguas lo usan."""
    embalaje = get_object_or_404(TipoEmbalaje, pk=pk)
    anterior = instantanea(embalaje)
    with transaction.atomic():
        embalaje.activo = not embalaje.activo
        embalaje.save(update_fields=["activo"])
        _registrar(request, embalaje, AccionAuditoria.MODIFICAR, anterior=anterior)
    estado = "activado" if embalaje.activo else "desactivado"
    messages.success(request, f"Tipo de embalaje «{embalaje.nombre}» {estado}.")
    return redirect("maestros:configuracion")
