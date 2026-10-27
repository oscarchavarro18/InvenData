"""Formularios del punto de venta. Validan lo que escribe la persona; las reglas de negocio
(existencia, factura repetida, autorización de datos...) las aplica el servicio."""

from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.auditoria.servicios import TIPOS_DE_EVIDENCIA
from apps.core.forms import EstiloMixin
from apps.maestros.models import Cliente, Producto


class LineaVentaForm(EstiloMixin, forms.Form):
    """Un producto de la vitrina y cuánto se lleva. Las filas vacías se ignoran."""

    producto = forms.ChoiceField(label="Producto", required=False)
    cantidad = forms.DecimalField(
        label="Cantidad (kg)",
        required=False,
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def __init__(self, *args, disponibles, **kwargs):
        super().__init__(*args, **kwargs)
        self.productos = {str(e.producto_id): e.producto for e in disponibles}
        self.fields["producto"].choices = [("", "—")] + [
            (str(e.producto_id), f"{e.producto.nombre} · {e.cantidad} kg disponibles")
            for e in disponibles
        ]
        for campo in self.fields.values():
            campo.widget.attrs["aria-label"] = campo.label

    def clean(self):
        datos = super().clean()
        elegido, cantidad = datos.get("producto"), datos.get("cantidad")
        if elegido and cantidad is None and "cantidad" not in self.errors:
            self.add_error("cantidad", "Indique cuánto se lleva.")
        if cantidad is not None and not elegido:
            self.add_error("producto", "Elija el producto.")
        datos["producto"] = self.productos.get(elegido) if elegido else None
        return datos


LineaVentaFormSet = forms.formset_factory(LineaVentaForm, extra=5, max_num=30)


class VentaConsumidorForm(EstiloMixin, forms.Form):
    numero_factura_siigo = forms.CharField(label="N.° de factura de Siigo", max_length=30)


class VentaRestauranteForm(EstiloMixin, forms.Form):
    cliente = forms.ModelChoiceField(
        label="Restaurante", queryset=Cliente.objects.filter(activo=True).order_by("razon_social")
    )
    autoriza_datos = forms.BooleanField(
        label=(
            "Le pregunté al cliente y autorizó el tratamiento de sus datos personales "
            "(Ley 1581 de 2012)"
        ),
        required=False,
    )
    evidencia = forms.FileField(
        label="Foto del formato de autorización firmado (recomendado)",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(sorted(TIPOS_DE_EVIDENCIA))}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].label_from_instance = lambda c: (
            f"{c.razon_social} · {c.tipo_documento} {c.numero_documento}"
            + ("" if c.autoriza_tratamiento_datos else " (sin autorización de datos)")
        )


class HistorialForm(EstiloMixin, forms.Form):
    desde = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.order_by("nombre"), required=False, empty_label="Todos"
    )

    def __init__(self, datos=None, **kwargs):
        hoy = timezone.localdate()
        inicial = {"desde": hoy - timedelta(days=7), "hasta": hoy}
        # Sin filtros en la URL, la última semana.
        super().__init__(datos if datos and "desde" in datos else None, initial=inicial, **kwargs)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos

    def rango(self):
        """Las fechas y el producto elegidos, o la última semana si no hay filtros válidos."""
        if self.is_bound and self.is_valid():
            datos = self.cleaned_data
            return datos["desde"], datos["hasta"], datos["producto"]
        return self.initial["desde"], self.initial["hasta"], None
