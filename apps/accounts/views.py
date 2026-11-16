"""Pantallas de usuarios en la Administración: solo el Gerente (RF-02)."""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts import servicios
from apps.accounts.forms import ClaveForm, UsuarioCrearForm, UsuarioEditarForm
from apps.accounts.models import Perfil, Usuario
from apps.auditoria.servicios import ip_de
from apps.core.paginacion import paginar
from apps.core.permisos import solo_gerente

AYUDA = (
    "Cada persona entra con su propio usuario. El administrador de punto de venta queda "
    "amarrado a su punto (RF-03); los demás perfiles no llevan ubicación."
)


@solo_gerente
def usuario_lista(request):
    usuarios = Usuario.objects.select_related("perfil", "ubicacion").order_by("usuario")
    q = request.GET.get("q", "").strip()
    if q:
        usuarios = usuarios.filter(Q(usuario__icontains=q) | Q(nombre_completo__icontains=q))
    perfil = request.GET.get("perfil", "")
    if perfil:
        usuarios = usuarios.filter(perfil__codigo=perfil)
    estado = request.GET.get("estado", "")
    if estado in ("activos", "inactivos"):
        usuarios = usuarios.filter(activo=estado == "activos")
    pagina, consulta = paginar(request, usuarios)
    contexto = {
        "pagina": pagina,
        "consulta": consulta,
        "q": q,
        "perfil": perfil,
        "estado": estado,
        "perfiles": Perfil.objects.order_by("nombre"),
    }
    return render(request, "administracion/usuario_lista.html", contexto)


def _volver():
    return {"volver": reverse("accounts:usuario_lista"), "volver_texto": "Volver a usuarios"}


@solo_gerente
def usuario_crear(request):
    form = UsuarioCrearForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        usuario = servicios.crear_usuario(form=form, actor=request.user, ip=ip_de(request))
        messages.success(request, f"Se creó el usuario «{usuario.usuario}».")
        return redirect("accounts:usuario_lista")
    contexto = {"form": form, "titulo": "Nuevo usuario", "ayuda": AYUDA, **_volver()}
    return render(request, "administracion/form.html", contexto)


@solo_gerente
def usuario_editar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    form = UsuarioEditarForm(request.POST if request.method == "POST" else None, instance=usuario)
    if request.method == "POST" and form.is_valid():
        try:
            servicios.editar_usuario(form=form, actor=request.user, ip=ip_de(request))
        except servicios.UsuarioInvalido as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, f"Se actualizó el usuario «{usuario.usuario}».")
            return redirect("accounts:usuario_lista")
    contexto = {
        "form": form,
        "titulo": f"Editar usuario {usuario.usuario}",
        "ayuda": AYUDA,
        **_volver(),
    }
    return render(request, "administracion/form.html", contexto)


@solo_gerente
@require_POST
def usuario_estado(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    try:
        activo = servicios.cambiar_estado_usuario(
            usuario=usuario, actor=request.user, ip=ip_de(request)
        )
    except servicios.UsuarioInvalido as error:
        messages.error(request, str(error))
    else:
        accion = "activó" if activo else "desactivó"
        messages.success(request, f"Se {accion} el usuario «{usuario.usuario}».")
    return redirect("accounts:usuario_lista")


@solo_gerente
def usuario_clave(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    form = ClaveForm(request.POST if request.method == "POST" else None, usuario=usuario)
    if request.method == "POST" and form.is_valid():
        servicios.cambiar_clave(
            usuario=usuario,
            clave=form.cleaned_data["clave"],
            actor=request.user,
            ip=ip_de(request),
        )
        messages.success(request, f"Se restableció la contraseña de «{usuario.usuario}».")
        return redirect("accounts:usuario_lista")
    contexto = {
        "form": form,
        "titulo": f"Contraseña de {usuario.usuario}",
        "ayuda": "Entréguela a la persona por un medio seguro y pídale que no la comparta.",
        **_volver(),
    }
    return render(request, "administracion/form.html", contexto)
