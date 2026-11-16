from decimal import Decimal

from apps.auditoria.servicios import instantanea, registrar
from apps.maestros.models import TipoEmbalaje


def test_registrar_guarda_el_registro_de_auditoria(gerente):
    registro = registrar(
        usuario=gerente,
        entidad="producto",
        registro_id=7,
        accion="MODIFICAR",
        valor_anterior={"activo": True},
        valor_nuevo={"activo": False},
        ip="10.0.0.5",
    )
    registro.refresh_from_db()
    assert registro.usuario == gerente
    assert registro.valor_anterior == {"activo": True}
    assert registro.valor_nuevo == {"activo": False}
    assert registro.direccion_ip == "10.0.0.5"


def test_instantanea_deja_decimales_como_texto_y_omite_id_y_fechas(db):
    tipo = TipoEmbalaje.objects.create(nombre="Canastilla", peso_tara=Decimal("1.85"))
    assert instantanea(tipo) == {"nombre": "Canastilla", "peso_tara": "1.85", "activo": True}
