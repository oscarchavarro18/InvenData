from decimal import Decimal

import pytest

from apps.maestros.models import TipoEmbalaje


@pytest.fixture
def canastilla(db):
    return TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("2.50"))


@pytest.fixture
def sin_embalaje(db):
    return TipoEmbalaje.objects.create(nombre="Sin embalaje", peso_tara=Decimal("0"))
