"""Administración de la auditoría y las evidencias (solo consulta).

Solo el Gerente entra al administrador de Django y consulta cualquier registro de auditoría
(RF-02, RF-10). Nadie crea, edita ni borra desde aquí: el registro lo escribe la aplicación
cuando ocurre cada acción.
"""

from django.contrib import admin

from .models import Auditoria, Evidencia


class SoloLecturaAdmin(admin.ModelAdmin):
    """Base para registros que se consultan, pero no se crean, editan ni borran a mano."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Auditoria)
class AuditoriaAdmin(SoloLecturaAdmin):
    list_display = ("fecha_hora", "usuario", "accion", "entidad", "registro_id")
    list_filter = ("accion", "entidad")
    list_select_related = ("usuario",)
    search_fields = ("entidad", "usuario__usuario", "usuario__nombre_completo")
    date_hierarchy = "fecha_hora"


@admin.register(Evidencia)
class EvidenciaAdmin(SoloLecturaAdmin):
    list_display = ("fecha_hora", "usuario", "entidad", "registro_id", "archivo")
    list_filter = ("entidad",)
    list_select_related = ("usuario",)
    search_fields = ("entidad", "usuario__usuario")
    date_hierarchy = "fecha_hora"
