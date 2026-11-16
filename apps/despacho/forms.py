"""Formularios del despacho. Validan lo que escribe la persona; las reglas de negocio
(estado del pedido, existencia, documento repetido...) las aplica el servicio."""

import json
from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.despacho.models import TipoDocumentoDespacho
from apps.despacho.servicios import TIPOS_DE_EVIDENCIA
from apps.embultaje.consultas import UBICACIONES_DE_ALISTAMIENTO
from apps.maestros.models import TipoUbicacion, Ubicacion


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


class TrasladoForm(EstiloMixin, forms.Form):
    """Encabezado del traslado a un PDV (RF-38). El origen se elige antes que los lotes."""

    ubicacion_origen = forms.ModelChoiceField(label="Sale de", queryset=Ubicacion.objects.none())
    ubicacion_destino = forms.ModelChoiceField(
        label="Punto de venta destino", queryset=Ubicacion.objects.none()
    )
    nombre_entrega = forms.CharField(label="Quién lo entrega físicamente", max_length=150)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        activas = Ubicacion.objects.filter(activo=True).order_by("codigo")
        self.fields["ubicacion_origen"].queryset = activas.filter(
            tipo__in=UBICACIONES_DE_ALISTAMIENTO
        )
        self.fields["ubicacion_destino"].queryset = activas.filter(tipo=TipoUbicacion.PUNTO_VENTA)
        for campo in ("ubicacion_origen", "ubicacion_destino"):
            self.fields[campo].label_from_instance = lambda ubicacion: ubicacion.nombre


class LineaTrasladoForm(EstiloMixin, forms.Form):
    """Un lote del origen y cuánto se envía. Las filas que quedan vacías se ignoran."""

    candidato = forms.ChoiceField(label="Lote", required=False)
    cantidad = forms.DecimalField(
        label="Cantidad (kg)",
        required=False,
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )

    def __init__(self, *args, candidatos, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidatos = {str(c.lote.pk): c for c in candidatos}
        self.fields["candidato"].choices = [("", "—")] + [
            (
                str(c.lote.pk),
                f"{c.lote.codigo} · {c.lote.producto.nombre} · {c.disponible} kg"
                f" · vence {c.lote.fecha_vencimiento:%d/%m/%Y}",
            )
            for c in candidatos
        ]
        for campo in self.fields.values():
            campo.widget.attrs["aria-label"] = campo.label

    def clean(self):
        datos = super().clean()
        elegido, cantidad = datos.get("candidato"), datos.get("cantidad")
        if elegido and cantidad is None and "cantidad" not in self.errors:
            self.add_error("cantidad", "Indique cuánto se envía de este lote.")
        if cantidad is not None and not elegido:
            self.add_error("candidato", "Elija el lote.")
        datos["lote"] = self.candidatos[elegido].lote if elegido else None
        return datos


LineaTrasladoFormSet = forms.formset_factory(LineaTrasladoForm, extra=5, max_num=50)


class VerificacionForm(EstiloMixin, forms.Form):
    """Lo que verifica el PDV al recibir: quién entrega y cuánto pesa cada línea (RF-41, RF-42)."""

    nombre_coincide = forms.BooleanField(
        label="Quien entrega es la persona indicada en el documento", required=False
    )
    observacion = forms.CharField(
        label="Observación (obligatoria para rechazar)",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args, detalles, **kwargs):
        super().__init__(*args, **kwargs)
        self.detalles = list(detalles)
        for detalle in self.detalles:
            self.fields[f"peso_{detalle.pk}"] = forms.DecimalField(
                label=f"Peso verificado del lote {detalle.lote.codigo} (kg)",
                required=False,
                max_digits=10,
                decimal_places=2,
                min_value=Decimal("0"),
            )
            self.fields[f"peso_{detalle.pk}"].widget.attrs["class"] = "form-control"

    def pesos(self):
        """Los pesos digitados, por línea; las que quedaron vacías no se incluyen."""
        return {
            d.pk: self.cleaned_data[f"peso_{d.pk}"]
            for d in self.detalles
            if self.cleaned_data.get(f"peso_{d.pk}") is not None
        }

    def campos_de_peso(self):
        return [(d, self[f"peso_{d.pk}"]) for d in self.detalles]


class ObservacionForm(EstiloMixin, forms.Form):
    observacion = forms.CharField(
        label="Nueva observación", max_length=500, widget=forms.Textarea(attrs={"rows": 2})
    )
