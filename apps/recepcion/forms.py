"""Formularios de recepción. Validan lo que escribe la persona; las reglas de negocio
(duplicados, documento cerrado...) las aplica el servicio."""

from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.core.forms import EstiloMixin
from apps.inventario.models import EstadoProducto
from apps.maestros.models import Producto, Proveedor, TipoEmbalaje, Ubicacion
from apps.recepcion.models import TipoDocumentoRecepcion
from apps.recepcion.servicios import UBICACIONES_DE_RECEPCION


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


class LoteForm(EstiloMixin, forms.Form):
    estado_producto = forms.ChoiceField(label="Estado", choices=EstadoProducto.choices)
    fecha_vencimiento = forms.DateField(
        label="Vence",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )


class TandaForm(EstiloMixin, forms.Form):
    """Una pesada: lo que baja del camión en un mismo embalaje, destino y temperatura."""

    tipo_embalaje = forms.ModelChoiceField(
        label="Embalaje", queryset=TipoEmbalaje.objects.filter(activo=True).order_by("nombre")
    )
    cantidad_embalajes = forms.IntegerField(label="Cant.", min_value=0, initial=1)
    peso_bruto = forms.DecimalField(
        label="Peso bruto (kg)", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    temperatura = forms.DecimalField(label="Temp. (°C)", max_digits=5, decimal_places=2)
    ubicacion_destino = forms.ModelChoiceField(
        label="Destino",
        queryset=Ubicacion.objects.filter(
            activo=True, tipo__in=sorted(UBICACIONES_DE_RECEPCION)
        ).order_by("codigo"),
    )
