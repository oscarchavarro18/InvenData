import pytest
from django.db import IntegrityError, transaction

from apps.maestros.models import Ubicacion


def test_tipo_de_ubicacion_invalido_lo_rechaza_la_base_de_datos(db):
    with pytest.raises(IntegrityError), transaction.atomic():
        Ubicacion.objects.create(codigo="X-01", nombre="Invalida", tipo="BODEGA_INEXISTENTE")


def test_codigo_de_ubicacion_es_unico(db, bodega):
    with pytest.raises(IntegrityError), transaction.atomic():
        Ubicacion.objects.create(codigo=bodega.codigo, nombre="Otra", tipo="SOSTENIMIENTO")
