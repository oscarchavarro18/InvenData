"""Formularios de embultaje. Validan lo que escribe la persona; las reglas de negocio
(lote disponible, existencia, ubicaciones...) las aplica el servicio."""

from decimal import Decimal

from django import forms

from apps.core.forms import EstiloMixin
from apps.maestros.models import TipoUbicacion, Ubicacion

MINIMO_KG = Decimal("0.01")


class RegistroForm(EstiloMixin, forms.Form):
    """Una tanda embultada: por bultos (cantidad × peso) o con el total digitado (RN-26)."""

    ubicacion_destino = forms.ModelChoiceField(label="Destino", queryset=Ubicacion.objects.none())
    usa_calculo_bultos = forms.BooleanField(
        label="Calcular por bultos (genera bultos numerados)", required=False
    )
    cantidad_bultos = forms.IntegerField(
        label="Cantidad de bultos", required=False, min_value=1, max_value=32767
    )
    peso_por_bulto = forms.DecimalField(
        label="Peso por bulto (kg)",
        required=False,
        max_digits=10,
        decimal_places=2,
        min_value=MINIMO_KG,
    )
    total_kilos = forms.DecimalField(
        label="Total embultado (kg)",
        required=False,
        max_digits=10,
        decimal_places=2,
        min_value=MINIMO_KG,
    )

    def __init__(self, *args, origen, **kwargs):
        super().__init__(*args, **kwargs)
        destinos = (
            Ubicacion.objects.filter(activo=True)
            .exclude(tipo=TipoUbicacion.PUNTO_VENTA)
            .exclude(pk=origen.pk)
            .order_by("codigo")
        )
        destino = self.fields["ubicacion_destino"]
        destino.queryset = destinos
        destino.label_from_instance = lambda ubicacion: ubicacion.nombre
        destino.initial = destinos.filter(tipo=TipoUbicacion.ZONA_BULTOS).first()

    def clean(self):
        datos = super().clean()
        if datos.get("usa_calculo_bultos"):
            for campo in ("cantidad_bultos", "peso_por_bulto"):
                if datos.get(campo) is None and campo not in self.errors:
                    self.add_error(campo, "Obligatorio al calcular por bultos.")
            datos["total_kilos"] = None  # se calcula: cantidad × peso
        else:
            if datos.get("total_kilos") is None and "total_kilos" not in self.errors:
                self.add_error("total_kilos", "Indique el total embultado.")
            datos["cantidad_bultos"] = datos["peso_por_bulto"] = None
        return datos
