"""Formularios de los maestros."""

from django import forms

from apps.core.forms import EstiloMixin
from apps.maestros.models import CategoriaProducto, Producto


class ProductoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            "codigo",
            "categoria",
            "nombre",
            "presentacion",
            "unidad_medida",
            "admite_transformacion",
        ]
        labels = {
            "codigo": "Código interno",
            "presentacion": "Presentación",
            "unidad_medida": "Unidad de medida",
            "categoria": "Categoría",
            "admite_transformacion": "Admite transformación (puede ser origen en M4)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaProducto.objects.filter(activa=True)
        self.fields["codigo"].widget.attrs["placeholder"] = "Ej. POL-001"
        self.fields["presentacion"].widget.attrs["placeholder"] = "Ej. Bandeja x 1 kg"

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()
