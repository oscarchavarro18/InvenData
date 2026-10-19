"""Piezas comunes de formularios: dan a cada campo las clases de estilo de la interfaz."""

from django import forms


class EstiloMixin:
    """Pone la clase de estilo adecuada a cada campo (texto, lista o casilla)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                clase = "form-check-input"
            elif isinstance(campo.widget, forms.Select):
                clase = "form-select"
            else:
                clase = "form-control"
            campo.widget.attrs["class"] = clase
