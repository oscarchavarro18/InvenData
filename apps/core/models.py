from django.db import models


class ModeloBase(models.Model):
    """Campos de fecha comunes a los maestros (creado_en / actualizado_en del Diccionario)."""

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        abstract = True


class ModeloCreacion(models.Model):
    """Tablas del Diccionario que solo llevan creado_en: documentos y líneas que no se editan."""

    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
