from django.db import models


class ModeloBase(models.Model):
    """Campos de fecha comunes a los maestros (creado_en / actualizado_en del Diccionario)."""

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        abstract = True
