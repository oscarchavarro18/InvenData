"""Formularios del conteo físico y de los ajustes y reversos de gerencia."""

from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.core.forms import EstiloMixin
from apps.inventario.models import MotivoAjuste
from apps.maestros.models import Producto, Ubicacion
from apps.puntoventa.models import SentidoMovimientoPdv


class ConteoForm(EstiloMixin, forms.Form):
    ubicacion = forms.ModelChoiceField(label="Ubicación", queryset=Ubicacion.objects.none())
    fecha = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        initial=timezone.localdate,
    )

    def __init__(self, *args, ubicaciones, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = ubicaciones
        self.fields["ubicacion"].label_from_instance = lambda u: u.nombre


class LineaConteoForm(EstiloMixin, forms.Form):
    """Un producto y cuántos bultos o cajas se contaron (RF-51). Filas vacías se ignoran."""

    producto = forms.ModelChoiceField(
        label="Producto",
        queryset=Producto.objects.filter(activo=True).order_by("nombre"),
        required=False,
    )
    cantidad_bultos = forms.IntegerField(label="Bultos o cajas", required=False, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            campo.widget.attrs["aria-label"] = campo.label

    def clean(self):
        datos = super().clean()
        producto, bultos = datos.get("producto"), datos.get("cantidad_bultos")
        if producto and bultos is None and "cantidad_bultos" not in self.errors:
            self.add_error("cantidad_bultos", "Indique cuántos bultos o cajas se contaron.")
        if bultos is not None and not producto:
            self.add_error("producto", "Elija el producto.")
        return datos


LineaConteoFormSet = forms.formset_factory(LineaConteoForm, extra=8, max_num=100)


class AjusteForm(EstiloMixin, forms.Form):
    """Ajuste manual del Gerente (RF-53): sentido, cantidad, motivo y justificación."""

    sentido = forms.ChoiceField(
        label="Sentido",
        choices=[
            (SentidoMovimientoPdv.SALIDA, "Resta (pérdida, vencimiento, error...)"),
            (SentidoMovimientoPdv.ENTRADA, "Suma (sobrante, error...)"),
        ],
    )
    cantidad = forms.DecimalField(
        label="Cantidad (kg)", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    motivo = forms.ChoiceField(label="Motivo", choices=MotivoAjuste.choices)
    observacion = forms.CharField(
        label="Justificación", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )


class AjustePdvForm(AjusteForm):
    """En el PDV se elige el producto: un sobrante puede ser de uno que no estaba."""

    producto = forms.ModelChoiceField(
        label="Producto", queryset=Producto.objects.filter(activo=True).order_by("nombre")
    )
    field_order = ["producto", "sentido", "cantidad", "motivo", "observacion"]


class ReversoForm(EstiloMixin, forms.Form):
    observacion = forms.CharField(
        label="Por qué se reversa", max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )
