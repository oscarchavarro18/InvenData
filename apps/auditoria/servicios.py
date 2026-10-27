"""Servicio de auditoría (RF-10): único punto por el que se escribe en la tabla auditoria."""

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import AccionAuditoria, Auditoria, Evidencia


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


# Evidencias (RF-16, RF-37): fotos o PDF de documentos firmados, de tamaño razonable.
TIPOS_DE_EVIDENCIA = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
TAMANO_MAXIMO_EVIDENCIA = 5 * 1024 * 1024


def validar_evidencia(archivo):
    """Falla con ValueError si el archivo no es una foto o un PDF de hasta 5 MB."""
    if getattr(archivo, "content_type", None) not in TIPOS_DE_EVIDENCIA:
        raise ValueError("La evidencia debe ser una foto (JPG, PNG o WebP) o un PDF.")
    if archivo.size > TAMANO_MAXIMO_EVIDENCIA:
        raise ValueError("La evidencia no puede pesar más de 5 MB.")


def guardar_evidencia(*, entidad, registro_id, archivo, usuario, ip=None):
    """Adjunta el archivo a un registro y deja constancia en auditoría. Ya validado."""
    evidencia = Evidencia.objects.create(
        entidad=entidad,
        registro_id=registro_id,
        archivo=archivo,
        tipo_mime=archivo.content_type,
        usuario=usuario,
    )
    registrar(
        usuario=usuario,
        entidad=Evidencia._meta.db_table,
        registro_id=evidencia.pk,
        accion=AccionAuditoria.CREAR,
        valor_nuevo={"entidad": entidad, "registro_id": registro_id},
        ip=ip,
    )
    return evidencia
