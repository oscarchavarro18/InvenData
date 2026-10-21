"""Formularios de los maestros."""

from django import forms

from apps.core.forms import EstiloMixin
from apps.maestros.models import CategoriaProducto, Producto, TipoEmbalaje


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


class EmbalajeForm(EstiloMixin, forms.ModelForm):
    """Tipo de embalaje con su peso de tara (RF-08). Tara cero = producto sin embalaje."""

    class Meta:
        model = TipoEmbalaje
        fields = ["nombre", "peso_tara"]
        labels = {"nombre": "Nombre", "peso_tara": "Peso de la tara (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].widget.attrs["placeholder"] = "Ej. Canastilla plástica"
        self.fields["peso_tara"].min_value = 0
        self.fields["peso_tara"].widget.attrs.update(
            {"min": "0", "step": "0.01", "inputmode": "decimal"}
        )

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        repetidos = TipoEmbalaje.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError("Ya existe un tipo de embalaje con ese nombre.")
        return nombre

    def clean_peso_tara(self):
        tara = self.cleaned_data["peso_tara"]
        if tara < 0:
            raise forms.ValidationError("La tara no puede ser negativa.")
        return tara
