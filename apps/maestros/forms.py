"""Formularios de los maestros."""

from django import forms
from django.utils import timezone

from apps.core.forms import EstiloMixin
from apps.inventario.models import Existencia, Movimiento
from apps.maestros.models import (
    CategoriaProducto,
    Cliente,
    Parametro,
    Producto,
    Proveedor,
    TipoEmbalaje,
    Ubicacion,
)
from apps.maestros.parametros import LECTORES
from apps.puntoventa.models import MovimientoPuntoVenta


def _espacios(texto):
    """Quita espacios repetidos y en los extremos."""
    return " ".join((texto or "").split())


def _repetido(modelo, instancia, **filtro):
    repetidos = modelo.objects.filter(**filtro)
    if instancia.pk:
        repetidos = repetidos.exclude(pk=instancia.pk)
    return repetidos.exists()


class ProductoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            "codigo",
            "categoria",
            "nombre",
            "presentacion",
            "unidad_medida",
            "admite_transformacion",
        ]
        labels = {
            "codigo": "Código interno",
            "presentacion": "Presentación",
            "unidad_medida": "Unidad de medida",
            "categoria": "Categoría",
            "admite_transformacion": "Admite transformación (puede ser origen en M4)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = CategoriaProducto.objects.filter(activa=True)
        self.fields["codigo"].widget.attrs["placeholder"] = "Ej. POL-001"
        self.fields["presentacion"].widget.attrs["placeholder"] = "Ej. Bandeja x 1 kg"

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()


class EmbalajeForm(EstiloMixin, forms.ModelForm):
    """Tipo de embalaje con su peso de tara (RF-08). Tara cero = producto sin embalaje."""

    class Meta:
        model = TipoEmbalaje
        fields = ["nombre", "peso_tara"]
        labels = {"nombre": "Nombre", "peso_tara": "Peso de la tara (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].widget.attrs["placeholder"] = "Ej. Canastilla plástica"
        self.fields["peso_tara"].min_value = 0
        self.fields["peso_tara"].widget.attrs.update(
            {"min": "0", "step": "0.01", "inputmode": "decimal"}
        )

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        repetidos = TipoEmbalaje.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError("Ya existe un tipo de embalaje con ese nombre.")
        return nombre

    def clean_peso_tara(self):
        tara = self.cleaned_data["peso_tara"]
        if tara < 0:
            raise forms.ValidationError("La tara no puede ser negativa.")
        return tara


class ParametroForm(forms.ModelForm):
    """Formulario del panel de gestión: valida los parámetros que el sistema interpreta.

    Un valor mal escrito, por ejemplo en la tolerancia de balance (RF-27), bloquearía todas
    las confirmaciones de transformación, así que se rechaza al guardarlo.
    """

    class Meta:
        model = Parametro
        fields = ["clave", "valor", "descripcion"]

    def clean(self):
        datos = super().clean()
        leer = LECTORES.get(datos.get("clave"))
        if leer is not None and datos.get("valor"):
            try:
                leer(datos["valor"])
            except ValueError as error:
                self.add_error("valor", str(error))
        return datos


class UbicacionForm(EstiloMixin, forms.ModelForm):
    """Zona de bodega o punto de venta (RF-05, RF-06). Abrir un PDV no exige cambiar código."""

    class Meta:
        model = Ubicacion
        fields = ["codigo", "nombre", "tipo"]
        labels = {"codigo": "Código", "nombre": "Nombre", "tipo": "Tipo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["codigo"].widget.attrs["placeholder"] = "Ej. PDV-03"
        self.fields["nombre"].widget.attrs["placeholder"] = "Ej. Punto de venta Centro"
        if self.instance.pk and self.en_uso():
            # Cambiar el tipo de una ubicación con historia mezclaría bodega y PDV.
            self.fields["tipo"].disabled = True
            self.fields["tipo"].help_text = "No se cambia: la ubicación ya tiene movimientos."

    def en_uso(self):
        u = self.instance
        return (
            Existencia.objects.filter(ubicacion=u).exists()
            or Movimiento.objects.filter(ubicacion_origen=u).exists()
            or Movimiento.objects.filter(ubicacion_destino=u).exists()
            or MovimientoPuntoVenta.objects.filter(ubicacion=u).exists()
        )

    def clean_codigo(self):
        return self.cleaned_data["codigo"].strip().upper()

    def clean_nombre(self):
        return _espacios(self.cleaned_data["nombre"])


class CategoriaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = CategoriaProducto
        fields = ["nombre"]
        labels = {"nombre": "Nombre de la categoría"}

    def clean_nombre(self):
        nombre = _espacios(self.cleaned_data["nombre"])
        if _repetido(CategoriaProducto, self.instance, nombre__iexact=nombre):
            raise forms.ValidationError("Ya existe una categoría con ese nombre.")
        return nombre


class _TerceroForm(EstiloMixin, forms.ModelForm):
    """Lo común a proveedores y clientes: documento único y razón social limpia."""

    def clean_numero_documento(self):
        return "".join(self.cleaned_data["numero_documento"].split()).upper()

    def clean_razon_social(self):
        return _espacios(self.cleaned_data["razon_social"])


class ProveedorForm(_TerceroForm):
    class Meta:
        model = Proveedor
        fields = ["tipo_documento", "numero_documento", "razon_social"]
        labels = {
            "tipo_documento": "Tipo de documento",
            "numero_documento": "Número de documento",
            "razon_social": "Razón social",
        }


class ClienteForm(_TerceroForm):
    """Cliente mayorista o restaurante, con la autorización de la Ley 1581 (RF-07, RNF-01)."""

    class Meta:
        model = Cliente
        fields = [
            "tipo_documento",
            "numero_documento",
            "razon_social",
            "autoriza_tratamiento_datos",
            "fecha_autorizacion",
        ]
        labels = {
            "tipo_documento": "Tipo de documento",
            "numero_documento": "Número de documento",
            "razon_social": "Razón social",
            "autoriza_tratamiento_datos": "Autorizó el tratamiento de sus datos (Ley 1581)",
            "fecha_autorizacion": "Fecha de la autorización",
        }
        widgets = {"fecha_autorizacion": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        datos = super().clean()
        autoriza = datos.get("autoriza_tratamiento_datos")
        fecha = datos.get("fecha_autorizacion")
        if autoriza and not fecha:
            self.add_error("fecha_autorizacion", "Indique la fecha en que el cliente autorizó.")
        if not autoriza and fecha:
            self.add_error(
                "fecha_autorizacion", "Sin autorización no se registra fecha de autorización."
            )
        if fecha and fecha > timezone.localdate():
            self.add_error("fecha_autorizacion", "La fecha de autorización no puede ser futura.")
        return datos


class ParametroValorForm(EstiloMixin, forms.ModelForm):
    """Cambiar el valor de un parámetro existente; la clave no se toca (la usa el código)."""

    class Meta:
        model = Parametro
        fields = ["valor", "descripcion"]
        labels = {"valor": "Valor", "descripcion": "Descripción"}

    def clean_valor(self):
        valor = self.cleaned_data["valor"].strip()
        leer = LECTORES.get(self.instance.clave)
        if leer is not None:
            try:
                leer(valor)
            except ValueError as error:
                raise forms.ValidationError(str(error)) from None
        return valor
