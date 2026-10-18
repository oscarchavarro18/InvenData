import pytest

from apps.accounts.models import Perfil, Usuario
from apps.maestros.models import Ubicacion


@pytest.fixture
def punto_venta(db):
    return Ubicacion.objects.create(codigo="PDV-01", nombre="Punto de venta 1", tipo="PUNTO_VENTA")


@pytest.fixture
def bodega(db):
    return Ubicacion.objects.create(
        codigo="SOST-01", nombre="Cuarto de sostenimiento", tipo="SOSTENIMIENTO"
    )


@pytest.fixture
def gerente(db):
    return Usuario.objects.create_superuser(
        "gerente", "ClaveSegura123", nombre_completo="Gerente de prueba"
    )


@pytest.fixture
def jefe_bodega(db):
    return Usuario.objects.create_user(
        "jefe",
        "ClaveSegura123",
        nombre_completo="Jefe de prueba",
        perfil=Perfil.objects.get(codigo="JEFE_BODEGA"),
    )
