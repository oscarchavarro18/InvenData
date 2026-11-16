"""Consulta de la auditoría en la Administración: solo el Gerente (RF-02, RF-10).

Es de solo lectura: ningún registro de auditoría se edita ni se borra (RNF-06, RNF-07).
"""

from django.shortcuts import get_object_or_404, render

from apps.auditoria import consultas
from apps.auditoria.forms import AuditoriaFiltrosForm
from apps.auditoria.models import Auditoria
from apps.core.paginacion import paginar
from apps.core.permisos import solo_gerente
from apps.reportes.consultas.comun import periodo
from apps.reportes.exportar import respuesta_csv, respuesta_pdf
from apps.reportes.reporte import Columna, Reporte


def _modulo(entidad):
    return consultas.nombre_de_entidad(entidad) if entidad else "Todos"


def _reporte(registros, valores):
    filas = [
        {
            "fecha": r.fecha_hora,
            "usuario": r.usuario.nombre_completo,
            "modulo": consultas.nombre_de_entidad(r.entidad),
            "registro": r.registro_id,
            "accion": r.get_accion_display(),
            "cambios": consultas.resumen_de_cambios(r),
            "ip": r.direccion_ip or "",
        }
        for r in registros
    ]
    return Reporte(
        titulo="Auditoría de operaciones",
        archivo="auditoria",
        columnas=[
            Columna("fecha", "Fecha y hora", "fechahora"),
            Columna("usuario", "Usuario"),
            Columna("modulo", "Módulo"),
            Columna("registro", "Registro", "entero"),
            Columna("accion", "Acción"),
            Columna("cambios", "Cambios"),
            Columna("ip", "Dirección IP"),
        ],
        filas=filas,
        filtros=[
            ("Periodo", periodo(valores["desde"], valores["hasta"])),
            ("Usuario", valores["usuario"].nombre_completo if valores["usuario"] else "Todos"),
            ("Módulo", _modulo(valores["entidad"])),
        ],
        resumen=[("Registros", len(filas), "entero")],
        nota="La auditoría no se edita ni se borra (RF-10, RNF-06).",
    )


@solo_gerente
def auditoria_lista(request):
    form = AuditoriaFiltrosForm(request.GET)
    valores = form.valores()
    registros = consultas.buscar(**valores)
    formato = request.GET.get("formato", "")
    if formato in ("csv", "pdf"):
        reporte = _reporte(registros, valores)
        return respuesta_csv(reporte) if formato == "csv" else respuesta_pdf(reporte, request.user)

    pagina, consulta = paginar(request, registros, por_pagina=30)
    for registro in pagina:
        registro.modulo = consultas.nombre_de_entidad(registro.entidad)
        registro.resumen = consultas.resumen_de_cambios(registro)
    exportar = request.GET.copy()
    for clave in ("pagina", "formato"):
        exportar.pop(clave, None)
    contexto = {
        "form": form,
        "pagina": pagina,
        "consulta": consulta,
        "exportar": exportar.urlencode(),
    }
    return render(request, "administracion/auditoria_lista.html", contexto)


@solo_gerente
def auditoria_detalle(request, pk):
    registro = get_object_or_404(Auditoria.objects.select_related("usuario"), pk=pk)
    contexto = {
        "registro": registro,
        "modulo": consultas.nombre_de_entidad(registro.entidad),
        "cambios": consultas.cambios(registro),
        "historia": consultas.buscar(entidad=registro.entidad, registro=registro.registro_id)[:20],
    }
    return render(request, "administracion/auditoria_detalle.html", contexto)
