"""Seguridad de M1: perfiles y usuarios (RF-01, RF-02, RF-03).

Usuario sigue la tabla `usuario` del Diccionario de datos. No usa PermissionsMixin: el alcance
de cada persona lo define su perfil (Gerente, Jefe de bodega, Administrador de punto de venta,
Consulta), tal como establece RF-02, y no grupos ni permisos sueltos.
"""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import ModeloBase
from apps.maestros.models import Ubicacion


class Perfil(models.Model):
    class Codigo(models.TextChoices):
        GERENTE = "GERENTE", "Gerente"
        JEFE_BODEGA = "JEFE_BODEGA", "Jefe de bodega"
        ADMIN_PDV = "ADMIN_PDV", "Administrador de punto de venta"
        CONSULTA = "CONSULTA", "Consulta"

    codigo = models.CharField(max_length=30, unique=True)  # nunca cambia; lo usa el código
    nombre = models.CharField(max_length=80, unique=True)  # texto visible, editable

    class Meta:
        db_table = "perfil"
        ordering = ["id"]

    def __str__(self):
        return self.nombre


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, usuario, password=None, **extra):
        if not usuario:
            raise ValueError("El usuario (nombre de acceso) es obligatorio.")
        if "perfil" not in extra and "perfil_id" not in extra:
            raise ValueError("Todo usuario debe tener un perfil.")
        user = self.model(usuario=usuario, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, usuario, password=None, **extra):
        """Equivale al perfil Gerente (control total, RF-02)."""
        extra["perfil"] = Perfil.objects.get(codigo=Perfil.Codigo.GERENTE)
        return self.create_user(usuario, password, **extra)


class Usuario(AbstractBaseUser, ModeloBase):
    perfil = models.ForeignKey(Perfil, on_delete=models.PROTECT, related_name="usuarios")
    # Solo el perfil Administrador de punto de venta lleva ubicación (RF-03).
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, null=True, blank=True, related_name="usuarios"
    )
    usuario = models.CharField(max_length=60, unique=True)  # nombre de acceso
    nombre_completo = models.CharField(max_length=150)
    password = models.CharField(max_length=128, db_column="contrasena_hash")  # hash, nunca texto
    activo = models.BooleanField(default=True)

    USERNAME_FIELD = "usuario"
    REQUIRED_FIELDS = ["nombre_completo"]
    objects = UsuarioManager()

    class Meta:
        db_table = "usuario"
        ordering = ["usuario"]

    def __str__(self):
        return f"{self.nombre_completo} ({self.usuario})"

    # --- Reglas de perfil (RF-02, RF-03) ---
    def clean(self):
        super().clean()
        if not self.perfil_id:
            return
        es_pdv = self.perfil.codigo == Perfil.Codigo.ADMIN_PDV
        if es_pdv and not (self.ubicacion_id and self.ubicacion.tipo == Ubicacion.Tipo.PUNTO_VENTA):
            raise ValidationError(
                {"ubicacion": "El administrador de punto de venta debe tener un punto de venta."}
            )
        if not es_pdv and self.ubicacion_id:
            raise ValidationError(
                {"ubicacion": "Solo el administrador de punto de venta lleva ubicación."}
            )

    # --- Integración con Django (admin y autenticación) ---
    @property
    def is_active(self):
        return self.activo

    @property
    def es_gerente(self):
        return self.activo and self.perfil.codigo == Perfil.Codigo.GERENTE

    @property
    def is_staff(self):
        return self.es_gerente

    @property
    def is_superuser(self):
        return self.es_gerente

    def has_perm(self, perm, obj=None):
        return self.es_gerente

    def has_module_perms(self, app_label):
        return self.es_gerente
