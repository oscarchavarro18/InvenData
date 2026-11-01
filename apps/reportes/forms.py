"""Filtros de los reportes de M9.

Todos los campos son opcionales: sin filtros en la URL el reporte sale con valores por
defecto (todo lo visible, o los últimos 30 días). Si un filtro no es válido se muestra el
error y el reporte usa los valores por defecto, nunca datos fuera del alcance de la persona.
"""

from django import forms

from apps.core.forms import EstiloMixin
from apps.inventario.consultas import DIAS_POR_VENCER
from apps.inventario.models import EstadoLote, MotivoAjuste
from apps.maestros.models import Producto, TipoUbicacion, Ubicacion
from apps.reportes.consultas import AGRUPACIONES, AMBITOS, CANALES, periodo_por_defecto

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _productos():
    return Producto.objects.order_by("nombre")


class FiltrosForm(EstiloMixin, forms.Form):
    """Base: se liga solo si la URL trae filtros y devuelve los valores con sus defectos."""

    def __init__(self, datos=None, **kwargs):
        campos = set(self.base_fields)
        ligado = datos is not None and any(k in campos for k in datos)
        super().__init__(datos if ligado else None, **kwargs)

    def valores(self):
        """Lo elegido, o el valor inicial de cada campo si no hay filtros o no son válidos."""
        iniciales = {n: self.get_initial_for_field(c, n) for n, c in self.fields.items()}
        if not (self.is_bound and self.is_valid()):
            return iniciales
        return {
            nombre: valor if valor not in (None, "") else iniciales[nombre]
            for nombre, valor in self.cleaned_data.items()
        }


class PeriodoMixin(forms.Form):
    desde = forms.DateField(label="Desde", required=False, widget=FECHA)
    hasta = forms.DateField(label="Hasta", required=False, widget=FECHA)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        desde, hasta = periodo_por_defecto()
        self.fields["desde"].initial = desde
        self.fields["hasta"].initial = hasta

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class ExistenciasBodegaForm(FiltrosForm):
    ubicacion = forms.ModelChoiceField(
        label="Ubicación", queryset=Ubicacion.objects.none(), required=False, empty_label="Todas"
    )
    producto = forms.ModelChoiceField(
        label="Producto", queryset=Producto.objects.none(), required=False, empty_label="Todos"
    )
    estado = forms.ChoiceField(
        label="Estado del lote",
        choices=[("", "Todos"), *EstadoLote.choices],
        required=False,
        initial="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = Ubicacion.objects.exclude(
            tipo=TipoUbicacion.PUNTO_VENTA
        ).order_by("codigo")
        self.fields["producto"].queryset = _productos()


class ExistenciasPdvForm(FiltrosForm):
    ubicacion = forms.ModelChoiceField(
        label="Punto de venta", queryset=Ubicacion.objects.none(), required=False
    )
    producto = forms.ModelChoiceField(
        label="Producto", queryset=Producto.objects.none(), required=False, empty_label="Todos"
    )

    def __init__(self, *args, puntos, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ubicacion"].queryset = puntos
        self.fields["ubicacion"].empty_label = "Todos" if puntos.count() > 1 else None
        self.fields["producto"].queryset = _productos()


class PorVencerForm(FiltrosForm):
    dias = forms.IntegerField(
        label="Vencen en (días)",
        min_value=0,
        max_value=365,
        required=False,
        initial=DIAS_POR_VENCER,
    )


class VentasForm(PeriodoMixin, ExistenciasPdvForm):
    canal = forms.ChoiceField(
        label="Canal", choices=list(CANALES.items()), required=False, initial=""
    )
    agrupar = forms.ChoiceField(
        label="Agrupar por",
        choices=[(k, titulo) for k, (titulo, _) in AGRUPACIONES.items()],
        required=False,
        initial="detalle",
    )

    field_order = ["desde", "hasta", "ubicacion", "producto", "canal", "agrupar"]


class CorreccionesForm(PeriodoMixin, FiltrosForm):
    ambito = forms.ChoiceField(
        label="Ámbito", choices=list(AMBITOS.items()), required=False, initial=""
    )
    motivo = forms.ChoiceField(
        label="Motivo", choices=[("", "Todos"), *MotivoAjuste.choices], required=False, initial=""
    )

    def __init__(self, *args, ver_bodega, ver_puntos, **kwargs):
        super().__init__(*args, **kwargs)
        # Quien ve un solo ámbito no elige ámbito: el reporte ya está limitado a él.
        if not (ver_bodega and ver_puntos):
            del self.fields["ambito"]
