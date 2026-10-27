"""Carga la tolerancia de balance de masa de M4 (RF-27). El Gerente la ajusta después (RN-09)."""

from django.db import migrations

CLAVE = "TOLERANCIA_BALANCE_PCT"


def crear_tolerancia(apps, schema_editor):
    Parametro = apps.get_model("maestros", "Parametro")
    Parametro.objects.get_or_create(
        clave=CLAVE,
        defaults={
            "valor": "5",
            "descripcion": (
                "Porcentaje de merma aceptado en una transformación sin observación (RF-27)."
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [("maestros", "0002_catalogos_base")]
    operations = [migrations.RunPython(crear_tolerancia, migrations.RunPython.noop)]
