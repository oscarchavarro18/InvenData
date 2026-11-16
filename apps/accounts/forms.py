"""Formularios de ingreso y de gestión de usuarios (RF-01 a RF-03)."""

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.accounts.models import Perfil, Usuario
from apps.core.forms import EstiloMixin
from apps.maestros.models import TipoUbicacion, Ubicacion


class IngresoForm(EstiloMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "Su usuario", "autofocus": True, "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Su contraseña", "autocomplete": "current-password"}
        )


class _UsuarioDatosForm(EstiloMixin, forms.ModelForm):
    """Nombre, perfil y punto de venta. El modelo exige el PDV al administrador (RF-03)."""

    class Meta:
        model = Usuario
        fields = ["nombre_completo", "perfil", "ubicacion"]
        labels = {
            "nombre_completo": "Nombre completo",
            "perfil": "Perfil",
            "ubicacion": "Punto de venta (solo para el administrador de PDV)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = Ubicacion.objects.filter(
            tipo=TipoUbicacion.PUNTO_VENTA, activo=True
        ).order_by("codigo")
        self.fields["ubicacion"].required = False
        self.fields["perfil"].queryset = Perfil.objects.order_by("nombre")

    def clean_nombre_completo(self):
        return " ".join(self.cleaned_data["nombre_completo"].split())


class _ClaveMixin:
    """Contraseña nueva con confirmación y los validadores de Django (RNF-04)."""

    def _validar_claves(self, usuario):
        clave = self.cleaned_data.get("clave")
        confirmacion = self.cleaned_data.get("confirmacion")
        if clave and confirmacion and clave != confirmacion:
            self.add_error("confirmacion", "Las contraseñas no coinciden.")
        elif clave:
            try:
                password_validation.validate_password(clave, usuario)
            except forms.ValidationError as error:
                self.add_error("clave", error)


def _campo_clave(etiqueta):
    return forms.CharField(
        label=etiqueta,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class UsuarioCrearForm(_ClaveMixin, _UsuarioDatosForm):
    clave = _campo_clave("Contraseña")
    confirmacion = _campo_clave("Repita la contraseña")

    class Meta(_UsuarioDatosForm.Meta):
        fields = ["usuario", "nombre_completo", "perfil", "ubicacion"]
        labels = {**_UsuarioDatosForm.Meta.labels, "usuario": "Usuario (para ingresar)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["usuario"].widget.attrs.update(
            {"placeholder": "Ej. maria.perez", "autocapitalize": "none", "autocomplete": "off"}
        )
        self.fields["clave"].help_text = password_validation.password_validators_help_text_html()

    def clean_usuario(self):
        usuario = self.cleaned_data["usuario"].strip().lower()
        if " " in usuario:
            raise forms.ValidationError("El usuario no lleva espacios.")
        if Usuario.objects.filter(usuario__iexact=usuario).exists():
            raise forms.ValidationError("Ya existe un usuario con ese nombre.")
        return usuario

    def clean(self):
        datos = super().clean()
        self._validar_claves(
            Usuario(usuario=datos.get("usuario", ""), nombre_completo=datos.get("nombre_completo"))
        )
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["clave"])
        if commit:
            usuario.save()
        return usuario


class UsuarioEditarForm(_UsuarioDatosForm):
    """El nombre de acceso no cambia: es la llave con la que la auditoría lo identifica."""


class ClaveForm(_ClaveMixin, EstiloMixin, forms.Form):
    clave = _campo_clave("Contraseña nueva")
    confirmacion = _campo_clave("Repita la contraseña nueva")

    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)
        self.fields["clave"].help_text = password_validation.password_validators_help_text_html()

    def clean(self):
        datos = super().clean()
        self._validar_claves(self.usuario)
        return datos
