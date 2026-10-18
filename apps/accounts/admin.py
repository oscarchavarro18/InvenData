from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Perfil, Usuario


class UsuarioCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ("usuario", "nombre_completo", "perfil", "ubicacion")


class UsuarioChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = "__all__"


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    form = UsuarioChangeForm
    add_form = UsuarioCreationForm
    list_display = ("usuario", "nombre_completo", "perfil", "ubicacion", "activo")
    list_filter = ("perfil", "activo")
    search_fields = ("usuario", "nombre_completo")
    ordering = ("usuario",)
    filter_horizontal = ()
    fieldsets = (
        (None, {"fields": ("usuario", "password")}),
        ("Datos", {"fields": ("nombre_completo", "perfil", "ubicacion", "activo")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "usuario",
                    "nombre_completo",
                    "perfil",
                    "ubicacion",
                    "password1",
                    "password2",
                ),
            },
        ),
    )


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre")
