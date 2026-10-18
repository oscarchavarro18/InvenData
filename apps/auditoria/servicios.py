"""Servicio de auditoría (RF-10): único punto por el que se escribe en la tabla auditoria."""

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import Auditoria


def instantanea(instancia):
    """Estado editable de un registro como diccionario listo para guardar en JSON.

    Las claves foráneas quedan como id; decimales y fechas, como texto. No incluye el id
    (va aparte, en registro_id) ni las fechas automáticas. Para modelos sin ManyToMany.
    """
    datos = model_to_dict(instancia, exclude=[instancia._meta.pk.name])
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))


def ip_de(request):
    """Dirección desde la que llega la petición, o None si no se conoce."""
    return request.META.get("REMOTE_ADDR") or None


def registrar(
    *, usuario, entidad, registro_id, accion, valor_anterior=None, valor_nuevo=None, ip=None
):
    """Guarda quién hizo qué y cuándo. La fecha la pone el propio modelo."""
    return Auditoria.objects.create(
        usuario=usuario,
        entidad=entidad,
        registro_id=registro_id,
        accion=accion,
        valor_anterior=valor_anterior,
        valor_nuevo=valor_nuevo,
        direccion_ip=ip,
    )
