from django.contrib import admin

from .models import Ubicacion


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "tipo", "activo")
    list_filter = ("tipo", "activo")
    search_fields = ("codigo", "nombre")
