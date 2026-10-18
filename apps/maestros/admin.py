"""Administración de los maestros de M1.

Solo el Gerente entra al administrador de Django (is_staff), así que estas pantallas son su
herramienta para mantener los catálogos. Cada alta y cada cambio queda en auditoría (RF-10).
"""

from django.contrib import admin

from apps.auditoria.mixins import AuditoriaAdminMixin

from .models import (
    CategoriaProducto,
    Cliente,
    Parametro,
    Producto,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)


class MaestroAdmin(AuditoriaAdminMixin, admin.ModelAdmin):
    """Base de los maestros: audita altas y cambios, y no permite borrar (RNF-06).

    Lo que ya no se usa se desactiva con el campo activo, en lugar de borrarse.
    """

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Ubicacion)
class UbicacionAdmin(MaestroAdmin):
    list_display = ("codigo", "nombre", "tipo", "activo")
    list_filter = ("tipo", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(CategoriaProducto)
class CategoriaProductoAdmin(MaestroAdmin):
    list_display = ("nombre", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Producto)
class ProductoAdmin(MaestroAdmin):
    list_display = (
        "codigo",
        "nombre",
        "presentacion",
        "unidad_medida",
        "categoria",
        "admite_transformacion",
        "activo",
    )
    list_filter = ("categoria", "unidad_medida", "admite_transformacion", "activo")
    list_select_related = ("categoria",)
    search_fields = ("codigo", "nombre")


@admin.register(Proveedor)
class ProveedorAdmin(MaestroAdmin):
    list_display = ("razon_social", "tipo_documento", "numero_documento", "activo")
    list_filter = ("tipo_documento", "activo")
    search_fields = ("razon_social", "numero_documento")


@admin.register(Cliente)
class ClienteAdmin(MaestroAdmin):
    list_display = (
        "razon_social",
        "tipo_documento",
        "numero_documento",
        "autoriza_tratamiento_datos",
        "activo",
    )
    list_filter = ("tipo_documento", "autoriza_tratamiento_datos", "activo")
    search_fields = ("razon_social", "numero_documento")


@admin.register(TipoEmbalaje)
class TipoEmbalajeAdmin(MaestroAdmin):
    list_display = ("nombre", "peso_tara", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(Parametro)
class ParametroAdmin(MaestroAdmin):
    list_display = ("clave", "valor", "descripcion")
    search_fields = ("clave", "descripcion")
