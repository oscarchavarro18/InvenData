"""Formularios de transformación. Validan lo que escribe la persona; las reglas de negocio
(producto transformable, saldo, tolerancia...) las aplica el servicio."""

from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.inventario.models import EstadoProducto
from apps.maestros.models import Producto, TipoUbicacion, Ubicacion

# Filas vacías que ofrece la pantalla de confirmación; las que quedan sin tocar se ignoran.
FILAS_DE_DERIVADOS = 4


def _zonas_de_bodega():
    return (
        Ubicacion.objects.filter(activo=True)
        .exclude(tipo=TipoUbicacion.PUNTO_VENTA)
        .order_by("codigo")
    )


class OrdenForm(EstiloMixin, forms.Form):
    """Encabezado de la orden: cuánto se consume del lote de origen (RF-23)."""

    cantidad_consumida = forms.DecimalField(
        label="Cantidad a consumir (kg)",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )


class DerivadoForm(EstiloMixin, forms.Form):
    """Un producto obtenido. El estado, el vencimiento y el destino se proponen del origen."""

    producto = forms.ModelChoiceField(
        label="Producto", queryset=Producto.objects.filter(activo=True)
    )
    cantidad = forms.DecimalField(
        label="Cantidad (kg)", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    ubicacion_destino = forms.ModelChoiceField(label="Destino", queryset=Ubicacion.objects.none())
    estado_producto = forms.ChoiceField(label="Estado", choices=EstadoProducto.choices)
    fecha_vencimiento = forms.DateField(
        label="Vence", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )

    def __init__(self, *args, orden, **kwargs):
        super().__init__(*args, **kwargs)
        destino = self.fields["ubicacion_destino"]
        destino.queryset = _zonas_de_bodega()
        destino.label_from_instance = lambda ubicacion: ubicacion.nombre
        # En la tabla no hay <label> por fila: el nombre del campo va en aria-label.
        for campo in self.fields.values():
            campo.widget.attrs["aria-label"] = campo.label
        # Como propuesta inicial, no como dato guardado: una fila que no se toca se ignora.
        lote = orden.lote_origen
        self.fields["producto"].initial = lote.producto_id
        self.fields["ubicacion_destino"].initial = orden.ubicacion_origen_id
        self.fields["estado_producto"].initial = lote.estado_producto
        self.fields["fecha_vencimiento"].initial = lote.fecha_vencimiento


DerivadoFormSet = forms.formset_factory(DerivadoForm, extra=FILAS_DE_DERIVADOS, max_num=20)


class ConfirmacionForm(EstiloMixin, forms.Form):
    observacion = forms.CharField(
        label="Observación",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obligatoria si el cierre se aparta de la tolerancia (RF-27).",
    )
