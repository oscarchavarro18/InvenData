"""Formulario de ingreso con el estilo de la interfaz."""

from django.contrib.auth.forms import AuthenticationForm

from apps.core.forms import EstiloMixin


class IngresoForm(EstiloMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"placeholder": "Su usuario", "autofocus": True, "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"placeholder": "Su contraseña", "autocomplete": "current-password"}
        )
