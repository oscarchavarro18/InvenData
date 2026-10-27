"""Restricciones de orden_transformacion y transformacion_derivado (RF-23 a RF-27)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.maestros.models import Parametro
from apps.transformacion.models import OrdenTransformacion, TransformacionDerivado


def test_las_tablas_siguen_el_diccionario_de_datos():
    assert OrdenTransformacion._meta.db_table == "orden_transformacion"
    assert TransformacionDerivado._meta.db_table == "transformacion_derivado"


def test_la_tolerancia_viene_cargada_por_migracion(db):
    assert Parametro.objects.get(clave="TOLERANCIA_BALANCE_PCT").valor == "5"


def _orden(**cambios):
    return OrdenTransformacion.objects.filter(pk=cambios.pop("pk")).update(**cambios)


@pytest.mark.parametrize(
    "cambios",
    [
        {"estado": "ANULADA"},
        {"cantidad_consumida": Decimal("0")},
        {"estado": "CONFIRMADA"},  # sin balance
        {"dentro_tolerancia": False, "observacion": None},
        {"dentro_tolerancia": False, "observacion": ""},
    ],
)
def test_la_base_rechaza_ordenes_incoherentes(orden, cambios):
    with pytest.raises(IntegrityError), transaction.atomic():
        _orden(pk=orden.pk, **cambios)


def test_fuera_de_tolerancia_con_observacion_es_valida(orden):
    _orden(pk=orden.pk, dentro_tolerancia=False, observacion="Producto con mucho hueso")
    orden.refresh_from_db()
    assert orden.dentro_tolerancia is False
