"""Auditoría y evidencias de M1 (RF-10, RF-16, RF-37).

El registro de auditoría es de solo inserción: la aplicación no actualiza ni borra filas.
Aquí queda quién hizo qué y cuándo; el historial del inventario vive en movimiento.
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.models import Q


class AccionAuditoria(models.TextChoices):
    CREAR = "CREAR", "Crear"
    MODIFICAR = "MODIFICAR", "Modificar"
    ANULAR = "ANULAR", "Anular"


class Auditoria(models.Model):
    """Quién hizo qué y cuándo, en todo el sistema (RF-10). Solo se inserta."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="auditorias"
    )
    fecha_hora = models.DateTimeField(auto_now_add=True)
    entidad = models.CharField(max_length=60)  # tabla afectada
    registro_id = models.PositiveBigIntegerField()  # id del registro afectado
    accion = models.CharField(max_length=10, choices=AccionAuditoria.choices)
    valor_anterior = models.JSONField(null=True, blank=True)
    valor_nuevo = models.JSONField(null=True, blank=True)
    direccion_ip = models.CharField(max_length=45, null=True, blank=True)

    class Meta:
        db_table = "auditoria"
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-fecha_hora"]
        indexes = [
            models.Index(fields=["entidad", "registro_id"], name="auditoria_entidad_registro_idx"),
            models.Index(fields=["fecha_hora"], name="auditoria_fecha_hora_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(accion__in=AccionAuditoria.values),
                name="auditoria_accion_valida",
            )
        ]

    def __str__(self):
        return f"{self.accion} {self.entidad} #{self.registro_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionDenied("Los registros de auditoría no se modifican.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Los registros de auditoría no se borran.")


class Evidencia(models.Model):
    """Adjuntos fotográficos de cualquier documento del sistema (RF-16, RF-37)."""

    entidad = models.CharField(max_length=60)  # tabla del documento al que se adjunta
    registro_id = models.PositiveBigIntegerField()  # id del documento
    archivo = models.FileField(upload_to="evidencias/%Y/%m/", max_length=255)
    tipo_mime = models.CharField(max_length=100, null=True, blank=True)
    fecha_hora = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="evidencias"
    )

    class Meta:
        db_table = "evidencia"
        verbose_name_plural = "evidencias"
        ordering = ["-fecha_hora"]
        indexes = [
            models.Index(fields=["entidad", "registro_id"], name="evidencia_entidad_registro_idx"),
        ]

    def __str__(self):
        return f"{self.entidad} #{self.registro_id}: {self.archivo.name}"
