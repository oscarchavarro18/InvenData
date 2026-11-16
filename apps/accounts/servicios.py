"""Gestión de usuarios desde la Administración del Gerente (RF-01 a RF-03, RF-10).

Las altas, los cambios, la activación y el cambio de contraseña quedan en auditoría sin la
contraseña. Dos reglas protegen el acceso al sistema: nadie se desactiva ni se quita el
perfil de Gerente a sí mismo, y siempre queda al menos un Gerente activo.
"""

from django.db import transaction

from apps.accounts.models import Perfil, Usuario
from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import registrar
from apps.maestros.servicios import MaestroInvalido, foto


class UsuarioInvalido(MaestroInvalido):
    """Una regla de acceso impide el cambio; el mensaje se muestra tal cual."""


def _auditar(actor, usuario, accion, ip, anterior=None, nuevo=None):
    registrar(
        usuario=actor,
        entidad=usuario._meta.db_table,
        registro_id=usuario.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=nuevo if nuevo is not None else foto(usuario),
        ip=ip,
    )


def _otros_gerentes_activos(usuario):
    return (
        Usuario.objects.select_for_update()
        .filter(perfil__codigo=Perfil.Codigo.GERENTE, activo=True)
        .exclude(pk=usuario.pk)
        .exists()
    )


@transaction.atomic
def crear_usuario(*, form, actor, ip=None):
    usuario = form.save()
    usuario.refresh_from_db()
    _auditar(actor, usuario, AccionAuditoria.CREAR, ip)
    return usuario


@transaction.atomic
def editar_usuario(*, form, actor, ip=None):
    """Cambia nombre, perfil o punto de venta. Sin cambios, no audita nada."""
    usuario = form.instance
    if not form.has_changed():
        return usuario
    anterior_bd = Usuario.objects.select_related("perfil").get(pk=usuario.pk)
    deja_de_ser_gerente = (
        anterior_bd.perfil.codigo == Perfil.Codigo.GERENTE
        and form.cleaned_data["perfil"].codigo != Perfil.Codigo.GERENTE
    )
    if deja_de_ser_gerente:
        if usuario.pk == actor.pk:
            raise UsuarioInvalido("No puede quitarse a sí mismo el perfil de Gerente.")
        if anterior_bd.activo and not _otros_gerentes_activos(usuario):
            raise UsuarioInvalido("Debe quedar al menos un Gerente activo en el sistema.")
    anterior = foto(anterior_bd)
    usuario = form.save()
    usuario.refresh_from_db()
    _auditar(actor, usuario, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return usuario


@transaction.atomic
def cambiar_estado_usuario(*, usuario, actor, ip=None):
    """Activa o desactiva el acceso. Un usuario inactivo no puede ingresar (RF-01)."""
    usuario = Usuario.objects.select_for_update().select_related("perfil").get(pk=usuario.pk)
    if usuario.activo:
        if usuario.pk == actor.pk:
            raise UsuarioInvalido("No puede desactivar su propio usuario.")
        if usuario.perfil.codigo == Perfil.Codigo.GERENTE and not _otros_gerentes_activos(usuario):
            raise UsuarioInvalido("Debe quedar al menos un Gerente activo en el sistema.")
    anterior = foto(usuario)
    usuario.activo = not usuario.activo
    usuario.save(update_fields=["activo"])
    _auditar(actor, usuario, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return usuario.activo


@transaction.atomic
def cambiar_clave(*, usuario, clave, actor, ip=None):
    """Asigna una contraseña nueva (guardada como hash). La auditoría dice que cambió, no cuál."""
    usuario = Usuario.objects.select_for_update().get(pk=usuario.pk)
    usuario.set_password(clave)
    usuario.save(update_fields=["password"])
    _auditar(
        actor,
        usuario,
        AccionAuditoria.MODIFICAR,
        ip,
        anterior={"contraseña": "anterior"},
        nuevo={"contraseña": "restablecida por el Gerente"},
    )
