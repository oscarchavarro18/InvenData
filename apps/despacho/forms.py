"""Formularios del despacho. Validan lo que escribe la persona; las reglas de negocio
(estado del pedido, existencia, documento repetido...) las aplica el servicio."""

import json
from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.despacho.models import TipoDocumentoDespacho
from apps.despacho.servicios import TIPOS_DE_EVIDENCIA


class DespachoForm(EstiloMixin, forms.Form):
    """Encabezado del documento que acompaña el furgón (RF-35)."""

    placa_vehiculo = forms.CharField(label="Placa", max_length=10)
    nombre_conductor = forms.CharField(label="Conductor", max_length=150)
    numero_sello = forms.CharField(label="Sello de seguridad", max_length=30, required=False)
    tipo_documento = forms.ChoiceField(
        label="Tipo de documento",
        choices=TipoDocumentoDespacho.choices,
        initial=TipoDocumentoDespacho.REMISION,
    )
    numero_documento = forms.CharField(label="Número de documento", max_length=30)
    valor_total = forms.DecimalField(
        label="Valor total (informativo)",
        required=False,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
    )


class LineaDespachoForm(EstiloMixin, forms.Form):
    """Lo realmente cargado de un lote alistado; parte de lo planeado y se puede ajustar."""

    alistamiento = forms.IntegerField(widget=forms.HiddenInput)
    cantidad = forms.DecimalField(
        label="Peso cargado (kg)", max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    cantidad_bultos_cajas = forms.IntegerField(
        label="Bultos o cajas", required=False, min_value=0, max_value=32767
    )


LineaDespachoFormSet = forms.formset_factory(LineaDespachoForm, extra=0)


class EntregaForm(EstiloMixin, forms.Form):
    """Constancia de entrega (RF-37): firma en pantalla, foto del papel firmado, o ambas."""

    nombre_recibe = forms.CharField(label="Nombre de quien recibe", max_length=150)
    firma = forms.CharField(widget=forms.HiddenInput, required=False)
    archivo = forms.FileField(
        label="Foto o PDF del documento firmado",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": ",".join(sorted(TIPOS_DE_EVIDENCIA))}),
    )

    def clean_firma(self):
        texto = self.cleaned_data["firma"].strip()
        if not texto:
            return None
        try:
            return json.loads(texto)
        except ValueError:
            raise forms.ValidationError("La firma digital no se pudo leer.") from None

    def clean(self):
        datos = super().clean()
        if not datos.get("firma") and not datos.get("archivo") and not self.errors:
            raise forms.ValidationError(
                "Capture la firma en pantalla o adjunte la foto del documento firmado."
            )
        return datos
