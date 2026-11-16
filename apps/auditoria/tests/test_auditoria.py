import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.auditoria.models import Auditoria, Evidencia


@pytest.fixture
def registro(gerente):
    return Auditoria.objects.create(
        usuario=gerente,
        entidad="producto",
        registro_id=1,
        accion="CREAR",
        valor_nuevo={"codigo": "POL-001"},
    )


def test_auditoria_guarda_fecha_y_valores_json(registro):
    registro.refresh_from_db()
    assert registro.fecha_hora is not None
    assert registro.valor_anterior is None
    assert registro.valor_nuevo == {"codigo": "POL-001"}


def test_accion_invalida_la_rechaza_la_base_de_datos(gerente):
    with pytest.raises(IntegrityError), transaction.atomic():
        Auditoria.objects.create(
            usuario=gerente, entidad="producto", registro_id=1, accion="BORRAR"
        )


def test_un_registro_de_auditoria_no_se_modifica(registro):
    registro.entidad = "otra_tabla"
    with pytest.raises(PermissionDenied):
        registro.save()


def test_un_registro_de_auditoria_no_se_borra(registro):
    with pytest.raises(PermissionDenied):
        registro.delete()
    assert Auditoria.objects.count() == 1


def test_no_se_puede_borrar_un_usuario_con_auditoria(registro, gerente):
    with pytest.raises(ProtectedError):
        gerente.delete()


def test_evidencia_guarda_la_ruta_del_archivo(gerente):
    evidencia = Evidencia.objects.create(
        usuario=gerente,
        entidad="despacho_mayorista",
        registro_id=5,
        archivo="evidencias/2026/10/remision.jpg",
        tipo_mime="image/jpeg",
    )
    evidencia.refresh_from_db()
    assert evidencia.archivo.name == "evidencias/2026/10/remision.jpg"


RUTAS_ADMIN = ["auditoria", "evidencia"]


@pytest.mark.parametrize("modelo", RUTAS_ADMIN)
def test_gerente_consulta_pero_no_crea(client, gerente, modelo):
    client.force_login(gerente)
    assert client.get(f"/admin/auditoria/{modelo}/").status_code == 200
    assert client.get(f"/admin/auditoria/{modelo}/add/").status_code == 403


@pytest.mark.parametrize("modelo", RUTAS_ADMIN)
def test_otros_perfiles_no_entran_a_la_auditoria(client, jefe_bodega, modelo):
    client.force_login(jefe_bodega)
    respuesta = client.get(f"/admin/auditoria/{modelo}/")
    assert respuesta.status_code == 302
    assert respuesta.url.startswith("/admin/login/")


def test_ni_el_gerente_edita_o_borra_desde_el_administrador(client, gerente, registro):
    client.force_login(gerente)
    assert client.post(f"/admin/auditoria/auditoria/{registro.pk}/change/", {}).status_code == 403
    assert client.get(f"/admin/auditoria/auditoria/{registro.pk}/delete/").status_code == 403
