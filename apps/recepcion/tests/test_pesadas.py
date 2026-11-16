from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.recepcion.models import Recepcion


@pytest.fixture
def datos_tanda(lote, canastilla, jefe_bodega, tunel):
    """Campos de una tanda válida: 5 canastillas con 50 kg brutos, a 3 °C."""
    return {
        "lote": lote,
        "tipo_embalaje": canastilla,
        "responsable": jefe_bodega,
        "ubicacion_destino": tunel,
        "cantidad_embalajes": 5,
        "peso_bruto": Decimal("50.00"),
        "temperatura": Decimal("3.00"),
    }


# --- Peso neto calculado -------------------------------------------------------


def test_el_peso_neto_descuenta_la_tara_de_los_embalajes(datos_tanda):
    tanda = Recepcion.objects.create(**datos_tanda)
    assert tanda.peso_neto == Decimal("37.50")  # 50 − 5 × 2.50


def test_el_peso_neto_queda_guardado_en_la_base(datos_tanda):
    tanda = Recepcion.objects.create(**datos_tanda)
    tanda.refresh_from_db()
    assert tanda.peso_neto == Decimal("37.50")


def test_producto_sin_embalaje_pesa_igual_bruto_y_neto(datos_tanda, sin_embalaje):
    datos_tanda.update(tipo_embalaje=sin_embalaje, cantidad_embalajes=0)
    tanda = Recepcion.objects.create(**datos_tanda)
    assert tanda.peso_neto == Decimal("50.00")


def test_tara_cero_ignora_la_cantidad_de_embalajes(datos_tanda, sin_embalaje):
    datos_tanda.update(tipo_embalaje=sin_embalaje, cantidad_embalajes=7)
    assert Recepcion.objects.create(**datos_tanda).peso_neto == Decimal("50.00")


def test_el_peso_neto_manda_el_calculo_aunque_se_intente_forzar(datos_tanda):
    tanda = Recepcion.objects.create(**datos_tanda, peso_neto=Decimal("99.00"))
    assert tanda.peso_neto == Decimal("37.50")


def test_el_peso_neto_no_cambia_si_despues_se_modifica_la_tara(datos_tanda, canastilla):
    tanda = Recepcion.objects.create(**datos_tanda)
    canastilla.peso_tara = Decimal("4.00")
    canastilla.save()
    tanda.refresh_from_db()
    tanda.temperatura = Decimal("4.00")
    tanda.save()
    assert tanda.peso_neto == Decimal("37.50")


def test_el_peso_bruto_se_acepta_como_texto(datos_tanda):
    datos_tanda["peso_bruto"] = "50.00"
    assert Recepcion.objects.create(**datos_tanda).peso_neto == Decimal("37.50")


# --- Varias tandas por lote ----------------------------------------------------


def test_un_lote_puede_tener_varias_tandas(datos_tanda, lote, sin_embalaje):
    Recepcion.objects.create(**datos_tanda)
    otra = {**datos_tanda, "tipo_embalaje": sin_embalaje, "cantidad_embalajes": 0}
    Recepcion.objects.create(**{**otra, "peso_bruto": Decimal("20.00")})
    pesos = [t.peso_neto for t in lote.tandas.all()]
    assert pesos == [Decimal("37.50"), Decimal("20.00")]
    assert sum(pesos) == Decimal("57.50")


def test_la_temperatura_admite_valores_bajo_cero(datos_tanda):
    datos_tanda["temperatura"] = Decimal("-18.50")
    tanda = Recepcion.objects.create(**datos_tanda)
    tanda.refresh_from_db()
    assert tanda.temperatura == Decimal("-18.50")


def test_la_tanda_se_muestra_con_el_codigo_del_lote(datos_tanda):
    tanda = Recepcion.objects.create(**datos_tanda)
    assert str(tanda) == f"Tanda {tanda.pk} del lote L-000001"


# --- Restricciones de la base de datos ----------------------------------------


@pytest.mark.parametrize("peso_bruto", [Decimal("0"), Decimal("-5.00")])
def test_el_peso_bruto_debe_ser_positivo(datos_tanda, peso_bruto):
    datos_tanda["peso_bruto"] = peso_bruto
    with pytest.raises(IntegrityError), transaction.atomic():
        Recepcion.objects.create(**datos_tanda)


def test_la_cantidad_de_embalajes_no_puede_ser_negativa(datos_tanda):
    datos_tanda["cantidad_embalajes"] = -1
    with pytest.raises(IntegrityError), transaction.atomic():
        Recepcion.objects.create(**datos_tanda)


@pytest.mark.parametrize("peso_bruto", [Decimal("12.50"), Decimal("10.00")])
def test_la_tara_no_puede_igualar_ni_superar_el_peso_bruto(datos_tanda, peso_bruto):
    datos_tanda["peso_bruto"] = peso_bruto  # 5 canastillas × 2.50 = 12.50 de tara
    with pytest.raises(IntegrityError), transaction.atomic():
        Recepcion.objects.create(**datos_tanda)


# --- Relaciones protegidas -----------------------------------------------------


def test_un_lote_con_tandas_no_se_puede_borrar(datos_tanda, lote):
    Recepcion.objects.create(**datos_tanda)
    with pytest.raises(ProtectedError):
        lote.delete()


def test_un_tipo_de_embalaje_usado_no_se_puede_borrar(datos_tanda, canastilla):
    Recepcion.objects.create(**datos_tanda)
    with pytest.raises(ProtectedError):
        canastilla.delete()
