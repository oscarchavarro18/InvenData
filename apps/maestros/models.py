"""Maestros de M1 (RF-02 a RF-08): catálogos que administra la gerencia.

Cada tabla usa el nombre del Diccionario de datos (db_table). Las listas cerradas del Diccionario
(tipo de ubicación, unidad de medida, tipo de documento) se aplican además como CHECK en la base
de datos, de modo que ningún dato inválido entre aunque se salte la aplicación.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import ModeloBase


class TipoUbicacion(models.TextChoices):
    TUNEL_CONGELACION = "TUNEL_CONGELACION", "Túnel de congelación"
    SOSTENIMIENTO = "SOSTENIMIENTO", "Cuarto de sostenimiento"
    ZONA_BULTOS = "ZONA_BULTOS", "Zona de bultos"
    ZONA_TRANSFORMACION = "ZONA_TRANSFORMACION", "Zona de transformación y reempaque"
    PUNTO_VENTA = "PUNTO_VENTA", "Punto de venta"


class UnidadMedida(models.TextChoices):
    KG = "KG", "Kilogramo"
    LB = "LB", "Libra"
    PAQUETE = "PAQUETE", "Paquete"


class TipoDocumentoProveedor(models.TextChoices):
    CC = "CC", "Cédula de ciudadanía"
    NIT = "NIT", "NIT"
    CE = "CE", "Cédula de extranjería"
    PAS = "PAS", "Pasaporte"


class TipoDocumentoCliente(models.TextChoices):
    NIT = "NIT", "NIT"
    CC = "CC", "Cédula de ciudadanía"
    CE = "CE", "Cédula de extranjería"


class Ubicacion(ModeloBase):
    """Zonas de la bodega y puntos de venta (RF-05, RF-06)."""

    Tipo = TipoUbicacion

    codigo = models.CharField(max_length=30, unique=True)  # estable, lo usa el código
    nombre = models.CharField(max_length=120, unique=True)  # texto para mostrar
    tipo = models.CharField(max_length=30, choices=TipoUbicacion.choices)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "ubicacion"
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"
        ordering = ["codigo"]
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=TipoUbicacion.values),
                name="ubicacion_tipo_valido",
            )
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class CategoriaProducto(ModeloBase):
    """Catálogo editable por gerencia, sin lista fija (RF-04)."""

    nombre = models.CharField(max_length=120, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "categoria_producto"
        verbose_name = "categoría de producto"
        verbose_name_plural = "categorías de producto"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Producto(ModeloBase):
    """Producto comercial (RF-04). `admite_transformacion` habilita su uso como origen en M4."""

    codigo = models.CharField(max_length=30, unique=True)  # código interno
    nombre = models.CharField(max_length=150)
    presentacion = models.CharField(max_length=100, null=True, blank=True)
    unidad_medida = models.CharField(max_length=10, choices=UnidadMedida.choices)
    categoria = models.ForeignKey(
        CategoriaProducto, on_delete=models.PROTECT, related_name="productos"
    )
    admite_transformacion = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "producto"
        ordering = ["codigo"]
        constraints = [
            models.CheckConstraint(
                condition=Q(unidad_medida__in=UnidadMedida.values),
                name="producto_unidad_valida",
            )
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class Proveedor(ModeloBase):
    """Quien entrega la mercancía en M2. Se identifica por tipo y número de documento."""

    tipo_documento = models.CharField(max_length=5, choices=TipoDocumentoProveedor.choices)
    numero_documento = models.CharField(max_length=30)
    razon_social = models.CharField(max_length=200)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["razon_social"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_documento", "numero_documento"],
                name="proveedor_documento_unico",
            ),
            models.CheckConstraint(
                condition=Q(tipo_documento__in=TipoDocumentoProveedor.values),
                name="proveedor_tipo_documento_valido",
            ),
        ]

    def __str__(self):
        return f"{self.razon_social} ({self.tipo_documento} {self.numero_documento})"


class Cliente(ModeloBase):
    """Cliente del punto de venta (RF-08). Guardar sus datos exige autorización (Ley 1581)."""

    tipo_documento = models.CharField(max_length=5, choices=TipoDocumentoCliente.choices)
    numero_documento = models.CharField(max_length=30)
    razon_social = models.CharField(max_length=200)
    autoriza_tratamiento_datos = models.BooleanField(default=False)
    fecha_autorizacion = models.DateField(null=True, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "cliente"
        ordering = ["razon_social"]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo_documento", "numero_documento"],
                name="cliente_documento_unico",
            ),
            models.CheckConstraint(
                condition=Q(tipo_documento__in=TipoDocumentoCliente.values),
                name="cliente_tipo_documento_valido",
            ),
            models.CheckConstraint(
                condition=Q(autoriza_tratamiento_datos=True) | Q(fecha_autorizacion__isnull=True),
                name="cliente_fecha_autorizacion_coherente",
            ),
        ]

    def clean(self):
        super().clean()
        if self.fecha_autorizacion and not self.autoriza_tratamiento_datos:
            raise ValidationError(
                {"fecha_autorizacion": "Solo hay fecha si el cliente autorizó el tratamiento."}
            )

    def __str__(self):
        return f"{self.razon_social} ({self.tipo_documento} {self.numero_documento})"


class TipoEmbalaje(ModeloBase):
    """Embalajes y su peso de tara, que se descuenta del peso bruto (RF-07)."""

    nombre = models.CharField(max_length=100)
    peso_tara = models.DecimalField(max_digits=10, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "tipo_embalaje"
        verbose_name = "tipo de embalaje"
        verbose_name_plural = "tipos de embalaje"
        ordering = ["nombre"]
        constraints = [
            models.CheckConstraint(
                condition=Q(peso_tara__gte=0),
                name="tipo_embalaje_tara_no_negativa",
            )
        ]

    def __str__(self):
        return f"{self.nombre} (tara {self.peso_tara})"


class Parametro(ModeloBase):
    """Ajustes del sistema que solo cambia el Gerente desde el administrador."""

    clave = models.CharField(max_length=80, unique=True)
    valor = models.CharField(max_length=200)
    descripcion = models.CharField(max_length=300, null=True, blank=True)

    class Meta:
        db_table = "parametro"
        ordering = ["clave"]

    def __str__(self):
        return f"{self.clave} = {self.valor}"
