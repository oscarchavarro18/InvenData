from apps.auditoria.models import Auditoria
from apps.maestros.models import CategoriaProducto

URL = "/admin/maestros/categoriaproducto/"


def test_crear_desde_el_administrador_queda_en_auditoria(client, gerente):
    client.force_login(gerente)
    respuesta = client.post(f"{URL}add/", {"nombre": "Camarón", "activa": "on"})
    assert respuesta.status_code == 302
    categoria = CategoriaProducto.objects.get(nombre="Camarón")
    registro = Auditoria.objects.get()
    assert registro.usuario == gerente
    assert registro.entidad == "categoria_producto"
    assert registro.registro_id == categoria.pk
    assert registro.accion == "CREAR"
    assert registro.valor_anterior is None
    assert registro.valor_nuevo == {"nombre": "Camarón", "activa": True}
    assert registro.direccion_ip == "127.0.0.1"


def test_desactivar_guarda_el_valor_anterior_y_el_nuevo(client, gerente):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    client.force_login(gerente)
    client.post(f"{URL}{categoria.pk}/change/", {"nombre": "Pollo"})  # sin "activa": desmarcada
    registro = Auditoria.objects.get()
    assert registro.accion == "MODIFICAR"
    assert registro.valor_anterior == {"nombre": "Pollo", "activa": True}
    assert registro.valor_nuevo == {"nombre": "Pollo", "activa": False}


def test_guardar_sin_cambios_no_genera_auditoria(client, gerente):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    client.force_login(gerente)
    client.post(f"{URL}{categoria.pk}/change/", {"nombre": "Pollo", "activa": "on"})
    assert Auditoria.objects.count() == 0


def test_los_maestros_no_se_borran_desde_el_administrador(client, gerente):
    categoria = CategoriaProducto.objects.create(nombre="Pollo")
    client.force_login(gerente)
    assert client.get(f"{URL}{categoria.pk}/delete/").status_code == 403
    assert CategoriaProducto.objects.filter(pk=categoria.pk).exists()
