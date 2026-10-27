"""Formularios del inventario. Validan lo que escribe la persona; las reglas de negocio
(saldo suficiente, destino activo...) las aplica el servicio."""

from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.maestros.models import TipoUbicacion, Ubicacion


class TrasladoForm(EstiloMixin, forms.Form):
    """Traslado interno de un lote desde una zona de la bodega a otra (RF-19)."""

    destino = forms.ModelChoiceField(label="Destino", queryset=Ubicacion.objects.none())
    cantidad = forms.DecimalField(
        label="Cantidad (kg)", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    observacion = forms.CharField(
        label="Observación",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, origen, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo zonas de bodega activas y distintas del origen: el punto de venta va por M6.
        self.fields["destino"].queryset = (
            Ubicacion.objects.filter(activo=True)
            .exclude(tipo=TipoUbicacion.PUNTO_VENTA)
            .exclude(pk=origen.pk)
            .order_by("codigo")
        )
