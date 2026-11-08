"""Pantallas de maestros: el catálogo de productos y la Administración del Gerente (M1).

El catálogo de productos lo consulta todo perfil. Todo lo demás (usuarios, ubicaciones,
categorías, clientes, proveedores, embalajes, parámetros y auditoría) vive en Administración
y es solo del Gerente (RF-02). Las vistas no escriben: llaman a `servicios.py`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.models import Usuario
from apps.auditoria.consultas import nombre_de_entidad
from apps.auditoria.models import Auditoria
from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import solo_gerente
from apps.maestros import servicios
from apps.maestros.catalogos import CATALOGOS
from apps.maestros.forms import ProductoForm
from apps.maestros.models import Producto


def _catalogo(clave):
    try:
        return CATALOGOS[clave]
    except KeyError:
        raise Http404 from None


# --- Catálogo de productos (lo consulta todo perfil, lo administra el Gerente) -----------


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


def _formulario_producto(request, producto):
    form = ProductoForm(request.POST if request.method == "POST" else None, instance=producto)
    if request.method == "POST" and form.is_valid():
        if producto is None:
            producto = servicios.crear(form=form, usuario=request.user, ip=ip_de(request))
            messages.success(request, f"Producto «{producto.nombre}» creado.")
        else:
            servicios.editar(form=form, usuario=request.user, ip=ip_de(request))
            messages.success(request, f"Producto «{producto.nombre}» actualizado.")
        return redirect("maestros:producto_lista")
    contexto = {
        "form": form,
        "titulo": "Editar producto" if producto else "Nuevo producto",
        "volver": reverse("maestros:producto_lista"),
        "volver_texto": "Volver a productos",
        "ayuda": "El código interno no se repite. Solo los productos que admiten "
        "transformación pueden ser origen de una orden (RF-23).",
    }
    return render(request, "administracion/form.html", contexto)


@solo_gerente  # los catálogos los administra la gerencia (RF-04)
def producto_crear(request):
    return _formulario_producto(request, None)


@solo_gerente
def producto_editar(request, pk):
    return _formulario_producto(request, get_object_or_404(Producto, pk=pk))


@solo_gerente
@require_POST
def producto_estado(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    try:
        activo = servicios.cambiar_estado(
            objeto=producto, campo="activo", usuario=request.user, ip=ip_de(request)
        )
    except servicios.MaestroInvalido as error:
        messages.error(request, str(error))
    else:
        estado = "activado" if activo else "desactivado"
        messages.success(request, f"Producto «{producto.nombre}» {estado}.")
    return redirect("maestros:producto_lista")


# --- Administración del Gerente --------------------------------------------------------


@solo_gerente
def administracion(request):
    """Resumen de todos los maestros con sus accesos y la actividad reciente (RF-02, RF-10)."""
    tarjetas = [
        {
            "titulo": "Usuarios",
            "descripcion": "Quién entra al sistema y con qué perfil.",
            "icono": "inicio",
            "url": reverse("accounts:usuario_lista"),
            "total": Usuario.objects.count(),
            "activos": Usuario.objects.filter(activo=True).count(),
        },
        {
            "titulo": "Productos",
            "descripcion": "Catálogo de productos y si admiten transformación.",
            "icono": "productos",
            "url": reverse("maestros:producto_lista"),
            "total": Producto.objects.count(),
            "activos": Producto.objects.filter(activo=True).count(),
        },
    ]
    for catalogo in CATALOGOS.values():
        consulta = catalogo.modelo.objects.all()
        activos = (
            consulta.filter(**{catalogo.campo_estado: True}).count()
            if catalogo.campo_estado
            else None
        )
        tarjetas.append(
            {
                "titulo": catalogo.plural,
                "descripcion": catalogo.descripcion,
                "icono": catalogo.icono,
                "url": reverse(catalogo.ruta("lista")),
                "total": consulta.count(),
                "activos": activos,
            }
        )
    recientes = list(Auditoria.objects.select_related("usuario")[:8])
    for registro in recientes:
        registro.modulo = nombre_de_entidad(registro.entidad)
    contexto = {
        "tarjetas": tarjetas,
        "recientes": recientes,
        "por_perfil": Usuario.objects.filter(activo=True)
        .values("perfil__nombre")
        .annotate(n=Count("id"))
        .order_by("perfil__nombre"),
    }
    return render(request, "administracion/inicio.html", contexto)


@solo_gerente
def catalogo_lista(request, clave):
    catalogo = _catalogo(clave)
    objetos = catalogo.modelo.objects.all().order_by(*catalogo.orden)
    q = request.GET.get("q", "").strip()
    if q:
        filtro = Q()
        for campo in catalogo.busqueda:
            filtro |= Q(**{campo: q})
        objetos = objetos.filter(filtro)
    estado = request.GET.get("estado", "")
    if catalogo.campo_estado and estado in ("activos", "inactivos"):
        objetos = objetos.filter(**{catalogo.campo_estado: estado == "activos"})
    pagina, consulta = paginar(request, objetos)
    filas = [
        {
            "objeto": objeto,
            "celdas": [(c.valor(objeto), c.estilo, c.titulo) for c in catalogo.columnas],
            "activo": getattr(objeto, catalogo.campo_estado) if catalogo.campo_estado else None,
            "editar": reverse(catalogo.ruta("editar"), args=[objeto.pk]),
            "estado": reverse(catalogo.ruta("estado"), args=[objeto.pk])
            if catalogo.campo_estado
            else None,
        }
        for objeto in pagina
    ]
    contexto = {
        "catalogo": catalogo,
        "pagina": pagina,
        "consulta": consulta,
        "filas": filas,
        "q": q,
        "estado": estado,
        "crear": reverse(catalogo.ruta("crear")) if catalogo.se_crea else None,
    }
    return render(request, "administracion/lista.html", contexto)


def _formulario(request, catalogo, objeto):
    form = catalogo.formulario(request.POST if request.method == "POST" else None, instance=objeto)
    if request.method == "POST" and form.is_valid():
        nombre = f"{catalogo.articulo} {catalogo.singular}"
        if objeto is None:
            objeto = servicios.crear(form=form, usuario=request.user, ip=ip_de(request))
            messages.success(request, f"Se creó {nombre} «{objeto}».")
        else:
            servicios.editar(form=form, usuario=request.user, ip=ip_de(request))
            messages.success(request, f"Se actualizó {nombre} «{objeto}».")
        return redirect(catalogo.ruta("lista"))
    contexto = {
        "form": form,
        "catalogo": catalogo,
        "titulo": f"Editar {catalogo.singular}" if objeto else catalogo.nuevo,
        "volver": reverse(catalogo.ruta("lista")),
        "volver_texto": f"Volver a {catalogo.plural.lower()}",
        "ayuda": catalogo.descripcion,
        "objeto": objeto,
    }
    return render(request, "administracion/form.html", contexto)


@solo_gerente
def catalogo_crear(request, clave):
    catalogo = _catalogo(clave)
    if not catalogo.se_crea:
        raise Http404
    return _formulario(request, catalogo, None)


@solo_gerente
def catalogo_editar(request, clave, pk):
    catalogo = _catalogo(clave)
    return _formulario(request, catalogo, get_object_or_404(catalogo.modelo, pk=pk))


@solo_gerente
@require_POST
def catalogo_estado(request, clave, pk):
    """Activa o desactiva: nada se borra, porque hay documentos que lo usan."""
    catalogo = _catalogo(clave)
    if not catalogo.campo_estado:
        raise Http404
    objeto = get_object_or_404(catalogo.modelo, pk=pk)
    try:
        activo = servicios.cambiar_estado(
            objeto=objeto, campo=catalogo.campo_estado, usuario=request.user, ip=ip_de(request)
        )
    except servicios.MaestroInvalido as error:
        messages.error(request, str(error))
    else:
        accion = "activó" if activo else "desactivó"
        messages.success(
            request, f"Se {accion} {catalogo.articulo} {catalogo.singular} «{objeto}»."
        )
    return redirect(catalogo.ruta("lista"))
