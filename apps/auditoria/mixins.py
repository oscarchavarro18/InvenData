"""Piezas reutilizables para auditar desde el administrador de Django (RF-10)."""

from .models import AccionAuditoria
from .servicios import instantanea, ip_de, registrar


class AuditoriaAdminMixin:
    """Registra en auditoría las altas y los cambios hechos desde el administrador."""

    def save_model(self, request, obj, form, change):
        valor_anterior = None
        if change:
            valor_anterior = instantanea(type(obj).objects.get(pk=obj.pk))
        super().save_model(request, obj, form, change)
        if change and not form.has_changed():
            return
        registrar(
            usuario=request.user,
            entidad=obj._meta.db_table,
            registro_id=obj.pk,
            accion=AccionAuditoria.MODIFICAR if change else AccionAuditoria.CREAR,
            valor_anterior=valor_anterior,
            valor_nuevo=instantanea(obj),
            ip=ip_de(request),
        )
