"""Consulta de la auditoría (RF-10, RNF-07). Aquí no se modifica nada.

La tabla guarda el nombre de la tabla afectada y los valores como JSON; estas funciones los
traducen a lo que entiende una persona: el nombre del módulo, el nombre de cada campo y qué
cambió de un valor al otro.
"""

from functools import cache

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist

from apps.auditoria.models import Auditoria
from apps.puntoventa.consultas import _rango


@cache
def _modelos_por_tabla():
    return {m._meta.db_table: m for m in apps.get_models()}


def nombre_de_entidad(tabla):
    """«documento_proveedor» → «Documento del proveedor»."""
    modelo = _modelos_por_tabla().get(tabla)
    if modelo is None:
        return tabla.replace("_", " ").capitalize()
    return str(modelo._meta.verbose_name).capitalize()


def entidades():
    """Los módulos que tienen registros, para el filtro, ordenados por nombre."""
    tablas = Auditoria.objects.values_list("entidad", flat=True).distinct().order_by()
    return sorted(((t, nombre_de_entidad(t)) for t in set(tablas)), key=lambda par: par[1])


def _etiqueta(modelo, campo):
    if modelo is not None:
        try:
            return str(modelo._meta.get_field(campo).verbose_name).capitalize()
        except FieldDoesNotExist:
            pass
    return campo.replace("_", " ").capitalize()


def _texto(valor):
    if valor is None or valor == "":
        return "-"
    if valor is True:
        return "Sí"
    if valor is False:
        return "No"
    return str(valor)


def cambios(registro):
    """Cada campo con su valor anterior y el nuevo, y si cambió. Los cambiados, primero."""
    modelo = _modelos_por_tabla().get(registro.entidad)
    anterior = registro.valor_anterior or {}
    nuevo = registro.valor_nuevo or {}
    filas = []
    for campo in list(dict.fromkeys([*anterior, *nuevo])):
        antes = anterior.get(campo)
        despues = nuevo.get(campo)
        filas.append(
            {
                "campo": _etiqueta(modelo, campo),
                "antes": _texto(antes) if registro.valor_anterior is not None else "",
                "despues": _texto(despues) if registro.valor_nuevo is not None else "",
                "cambio": registro.valor_anterior is not None and antes != despues,
            }
        )
    filas.sort(key=lambda f: not f["cambio"])
    return filas


def resumen_de_cambios(registro):
    """Una línea: «Tara: 2.50 > 2.75; Activo: Sí > No» o «Registro nuevo»."""
    if registro.valor_anterior is None:
        return "Registro nuevo"
    partes = [
        f"{f['campo']}: {f['antes']} > {f['despues']}" for f in cambios(registro) if f["cambio"]
    ]
    return "; ".join(partes) or "Sin cambios de valor"


def buscar(*, desde=None, hasta=None, usuario=None, entidad="", accion="", registro=None):
    """Los registros que cumplen los filtros, del más reciente al más antiguo."""
    registros = Auditoria.objects.select_related("usuario")
    if desde and hasta:
        inicio, fin = _rango(desde, hasta)
        registros = registros.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
    if usuario is not None:
        registros = registros.filter(usuario=usuario)
    if entidad:
        registros = registros.filter(entidad=entidad)
    if accion:
        registros = registros.filter(accion=accion)
    if registro:
        registros = registros.filter(registro_id=registro)
    return registros.order_by("-fecha_hora", "-id")
