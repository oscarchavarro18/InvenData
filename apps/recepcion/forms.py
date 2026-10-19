"""Formularios de recepción. Validan lo que escribe la persona; las reglas de negocio
(duplicados, documento cerrado...) las aplica el servicio."""

from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.core.forms import EstiloMixin
from apps.maestros.models import Producto, Proveedor
from apps.recepcion.models import TipoDocumentoRecepcion


class DocumentoForm(EstiloMixin, forms.Form):
    proveedor = forms.ModelChoiceField(queryset=Proveedor.objects.filter(activo=True))
    tipo_documento = forms.ChoiceField(label="Tipo", choices=TipoDocumentoRecepcion.choices)
    numero_documento = forms.CharField(label="Número", max_length=30)
    fecha = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        initial=timezone.localdate,
    )


class LineaForm(EstiloMixin, forms.Form):
    producto = forms.ModelChoiceField(queryset=Producto.objects.filter(activo=True))
    cantidad = forms.DecimalField(
        label="Cantidad declarada (kg)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
