"""Carga los cuatro perfiles del sistema (RF-02). Son datos de referencia, no de prueba."""
from django.db import migrations

PERFILES = [
    ("GERENTE", "Gerente"),
    ("JEFE_BODEGA", "Jefe de bodega"),
    ("ADMIN_PDV", "Administrador de punto de venta"),
    ("CONSULTA", "Consulta"),
]


def crear_perfiles(apps, schema_editor):
    Perfil = apps.get_model("accounts", "Perfil")
    for codigo, nombre in PERFILES:
        Perfil.objects.update_or_create(codigo=codigo, defaults={"nombre": nombre})


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(crear_perfiles, migrations.RunPython.noop)]
