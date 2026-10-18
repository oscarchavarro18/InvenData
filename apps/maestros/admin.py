"""Administración de los maestros de M1.

Solo el Gerente entra al administrador de Django (is_staff), así que estas pantallas son su
herramienta para mantener los catálogos.
"""

from django.contrib import admin

from .models import (
    CategoriaProducto,
    Cliente,
    Parametro,
    Producto,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "tipo", "activo")
    list_filter = ("tipo", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(CategoriaProducto)
class CategoriaProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
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
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("razon_social", "tipo_documento", "numero_documento", "activo")
    list_filter = ("tipo_documento", "activo")
    search_fields = ("razon_social", "numero_documento")


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
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
class TipoEmbalajeAdmin(admin.ModelAdmin):
    list_display = ("nombre", "peso_tara", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("clave", "valor", "descripcion")
    search_fields = ("clave", "descripcion")
