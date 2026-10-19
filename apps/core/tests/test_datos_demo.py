import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Usuario
from apps.maestros.models import Producto, TipoEmbalaje, Ubicacion
from apps.recepcion.models import DocumentoProveedor, DocumentoProveedorLinea


@pytest.fixture
def cargar(db):
    def _cargar(clave="ClaveDemo12345"):
        call_command("cargar_datos_demo", clave=clave)

    return _cargar


def test_crea_los_datos_de_demostracion(cargar):
    cargar()
    assert Ubicacion.objects.count() == 5
    assert TipoEmbalaje.objects.count() == 3
    assert Producto.objects.count() == 3
    assert DocumentoProveedor.objects.get().estado == "ABIERTO"
    assert DocumentoProveedorLinea.objects.count() == 2


def test_crea_el_gerente_y_el_jefe_de_bodega(cargar):
    cargar()
    assert Usuario.objects.get(usuario="gerente").es_gerente
    jefe = Usuario.objects.get(usuario="jefe")
    assert jefe.perfil.codigo == "JEFE_BODEGA"
    assert jefe.check_password("ClaveDemo12345")


def test_se_puede_repetir_sin_duplicar(cargar):
    cargar()
    cargar()
    assert Ubicacion.objects.count() == 5
    assert Producto.objects.count() == 3
    assert Usuario.objects.count() == 2
    assert DocumentoProveedor.objects.count() == 1
    assert DocumentoProveedorLinea.objects.count() == 2


def test_no_cambia_la_contrasena_de_un_usuario_existente(cargar):
    cargar("PrimeraClave123")
    cargar("OtraClaveDistinta1")
    assert Usuario.objects.get(usuario="jefe").check_password("PrimeraClave123")


def test_exige_la_clave(db):
    with pytest.raises(CommandError):
        call_command("cargar_datos_demo")
