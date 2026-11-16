"""Formularios del levantamiento de inventario inicial. Las reglas las aplica el servicio."""

from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.inventario.models import EstadoLote, EstadoProducto
from apps.maestros.models import Producto

MINIMO_KG = Decimal("0.01")


def _productos():
    return Producto.objects.filter(activo=True).order_by("nombre")


class LoteContadoForm(EstiloMixin, forms.Form):
    """Un lote que ya estaba en la zona de bodega al arrancar (RF-62)."""

    producto = forms.ModelChoiceField(queryset=_productos())
    estado_producto = forms.ChoiceField(label="Estado", choices=EstadoProducto.choices)
    fecha_vencimiento = forms.DateField(
        label="Vence", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    cantidad = forms.DecimalField(
        label="Cantidad (kg)", max_digits=10, decimal_places=2, min_value=MINIMO_KG
    )
    estado_lote_resultante = forms.ChoiceField(
        label="¿Ya está embultado?",
        choices=[
            (EstadoLote.DISPONIBLE, "No: producto crudo o en caja"),
            (EstadoLote.EMBULTADO, "Sí: ya está en bultos"),
        ],
    )
    cantidad_bultos = forms.IntegerField(
        label="Bultos (si ya está embultado)", required=False, min_value=0, max_value=32767
    )

    def clean(self):
        datos = super().clean()
        if datos.get("estado_lote_resultante") != EstadoLote.EMBULTADO:
            datos["cantidad_bultos"] = None  # solo informa cuando ya está embultado
        return datos


class ProductoContadoForm(EstiloMixin, forms.Form):
    """Un producto que ya estaba en la vitrina del punto de venta al arrancar (SN-09)."""

    producto = forms.ModelChoiceField(queryset=_productos())
    cantidad = forms.DecimalField(
        label="Cantidad (kg)", max_digits=10, decimal_places=2, min_value=MINIMO_KG
    )
