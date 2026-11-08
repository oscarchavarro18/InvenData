"""Escrituras de los maestros desde la Administración del Gerente (RF-02, RF-04 a RF-08).

Toda alta, cambio o activación pasa por aquí, dentro de una transacción y con su registro
de auditoría en la misma transacción (RF-10). Nada se borra: un maestro que ya se usó se
desactiva, porque hay documentos y movimientos que lo referencian.
"""

from django.db import transaction
from django.db.models import Sum

from apps.auditoria.models import AccionAuditoria
from apps.auditoria.servicios import instantanea, registrar
from apps.inventario.models import Existencia
from apps.maestros.models import CategoriaProducto, Producto, Ubicacion
from apps.puntoventa.models import ExistenciaPuntoVenta


class MaestroInvalido(Exception):
    """Una regla de negocio impide el cambio; el mensaje se muestra tal cual."""


def foto(objeto):
    """Lo que se guarda en auditoría de un registro (sin contraseña ni datos sensibles)."""
    return instantanea(objeto)


def _auditar(usuario, objeto, accion, ip, anterior=None):
    objeto.refresh_from_db()
    registrar(
        usuario=usuario,
        entidad=objeto._meta.db_table,
        registro_id=objeto.pk,
        accion=accion,
        valor_anterior=anterior,
        valor_nuevo=foto(objeto),
        ip=ip,
    )


@transaction.atomic
def crear(*, form, usuario, ip=None):
    """Guarda el formulario ya validado y deja la alta en auditoría. Devuelve el objeto."""
    objeto = form.save()
    _auditar(usuario, objeto, AccionAuditoria.CREAR, ip)
    return objeto


@transaction.atomic
def editar(*, form, usuario, ip=None):
    """Guarda los cambios con el valor anterior y el nuevo. Sin cambios, no audita nada."""
    if not form.has_changed():
        return form.instance
    anterior = foto(type(form.instance).objects.get(pk=form.instance.pk))
    objeto = form.save()
    _auditar(usuario, objeto, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return objeto


def _existencia_de_producto(producto):
    bodega = Existencia.objects.filter(lote__producto=producto).aggregate(t=Sum("cantidad"))["t"]
    puntos = ExistenciaPuntoVenta.objects.filter(producto=producto).aggregate(t=Sum("cantidad"))
    return (bodega or 0) + (puntos["t"] or 0)


def _existencia_en_ubicacion(ubicacion):
    bodega = Existencia.objects.filter(ubicacion=ubicacion).aggregate(t=Sum("cantidad"))["t"]
    puntos = ExistenciaPuntoVenta.objects.filter(ubicacion=ubicacion).aggregate(t=Sum("cantidad"))
    return (bodega or 0) + (puntos["t"] or 0)


def validar_desactivacion(objeto):
    """Lo que impide desactivar un maestro sin dejar inventario o personas huérfanos."""
    if isinstance(objeto, Ubicacion):
        kg = _existencia_en_ubicacion(objeto)
        if kg > 0:
            raise MaestroInvalido(
                f"{objeto.nombre} todavía tiene {kg} kg de existencia. Trasládelos o ajústelos "
                "antes de desactivarla."
            )
        if objeto.usuarios.filter(activo=True).exists():
            raise MaestroInvalido(
                f"{objeto.nombre} tiene usuarios activos asignados. Desactívelos o cámbielos "
                "de punto de venta primero."
            )
    elif isinstance(objeto, Producto):
        kg = _existencia_de_producto(objeto)
        if kg > 0:
            raise MaestroInvalido(
                f"{objeto.nombre} todavía tiene {kg} kg de existencia. No se puede desactivar "
                "un producto con inventario."
            )
    elif isinstance(objeto, CategoriaProducto):
        if objeto.productos.filter(activo=True).exists():
            raise MaestroInvalido(
                f"La categoría {objeto.nombre} tiene productos activos. Desactívelos o "
                "muévalos a otra categoría primero."
            )


@transaction.atomic
def cambiar_estado(*, objeto, campo, usuario, ip=None):
    """Activa o desactiva un maestro (el campo `activo` o `activa`). Devuelve el nuevo estado."""
    objeto = type(objeto).objects.select_for_update().get(pk=objeto.pk)
    activo = getattr(objeto, campo)
    if activo:
        validar_desactivacion(objeto)
    anterior = foto(objeto)
    setattr(objeto, campo, not activo)
    objeto.save(update_fields=[campo])
    _auditar(usuario, objeto, AccionAuditoria.MODIFICAR, ip, anterior=anterior)
    return not activo
