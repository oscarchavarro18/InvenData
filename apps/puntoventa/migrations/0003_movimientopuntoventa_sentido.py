"""Agrega el sentido (entrada o salida) a cada movimiento del punto de venta (M8).

Escrita a mano en tres pasos porque la tabla puede tener datos: se agrega la columna vacía,
se llena según el tipo de cada movimiento ya registrado (las ventas restan, lo demás sumaba)
y luego se vuelve obligatoria y se le ponen sus restricciones.
"""

from django.db import migrations, models

SENTIDOS = [("ENTRADA", "Entrada"), ("SALIDA", "Salida")]


def llenar_sentido(apps, schema_editor):
    Movimiento = apps.get_model("puntoventa", "MovimientoPuntoVenta")
    Movimiento.objects.filter(tipo="VENTA").update(sentido="SALIDA")
    Movimiento.objects.exclude(tipo="VENTA").update(sentido="ENTRADA")


class Migration(migrations.Migration):
    dependencies = [
        ("puntoventa", "0002_ventaconsumidorfinal_ventaconsumidorfinallinea_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="movimientopuntoventa",
            name="sentido",
            field=models.CharField(choices=SENTIDOS, max_length=7, null=True),
        ),
        migrations.RunPython(llenar_sentido, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="movimientopuntoventa",
            name="sentido",
            field=models.CharField(choices=SENTIDOS, max_length=7),
        ),
        migrations.AddConstraint(
            model_name="movimientopuntoventa",
            constraint=models.CheckConstraint(
                condition=models.Q(sentido__in=["ENTRADA", "SALIDA"]),
                name="mov_pdv_sentido_valido",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientopuntoventa",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        tipo__in=["ENTRADA_TRASLADO", "INVENTARIO_INICIAL"], sentido="ENTRADA"
                    )
                    | models.Q(tipo="VENTA", sentido="SALIDA")
                    | models.Q(tipo="AJUSTE_CONTEO")
                ),
                name="mov_pdv_sentido_coherente",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientopuntoventa",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        ~models.Q(motivo_ajuste__in=["PERDIDA", "VENCIMIENTO"])
                        | models.Q(sentido="SALIDA")
                    )
                    & (~models.Q(motivo_ajuste="SOBRANTE") | models.Q(sentido="ENTRADA"))
                ),
                name="mov_pdv_sentido_del_motivo",
            ),
        ),
        migrations.AddConstraint(
            model_name="movimientopuntoventa",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(movimiento_punto_venta_reversado__isnull=True)
                    | models.Q(tipo="AJUSTE_CONTEO", motivo_ajuste="ERROR_CONTEO")
                ),
                name="mov_pdv_reverso_es_ajuste_por_error",
            ),
        ),
    ]
