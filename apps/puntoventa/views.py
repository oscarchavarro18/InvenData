"""Pantallas del punto de venta (M7).

El administrador de punto de venta solo ve su propia ubicación; el Gerente y el perfil
Consulta pueden elegir cualquier PDV (RF-03, RN-06, RN-07).
"""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.core.paginacion import paginar
from apps.maestros.models import TipoUbicacion, Ubicacion
from apps.puntoventa.models import ExistenciaPuntoVenta


@login_required
def existencias(request):
    """Cuánto hay de cada producto en un punto de venta, en tiempo real (RF-48)."""
    usuario = request.user
    if not usuario.ve_algun_punto_venta:
        raise PermissionDenied
    if usuario.es_admin_pdv:
        puntos = Ubicacion.objects.filter(pk=usuario.ubicacion_id)
    else:
        puntos = Ubicacion.objects.filter(tipo=TipoUbicacion.PUNTO_VENTA).order_by("codigo")
    elegido = request.GET.get("ubicacion", "")
    # Si pide un punto que no le corresponde, ve el suyo (o el primero, si ve todos).
    punto = (puntos.filter(pk=elegido).first() if elegido.isdigit() else None) or puntos.first()
    filas = ExistenciaPuntoVenta.objects.none()
    if punto is not None:
        if not usuario.ve_punto_venta(punto):
            raise PermissionDenied
        filas = (
            ExistenciaPuntoVenta.objects.filter(ubicacion=punto, cantidad__gt=0)
            .select_related("producto")
            .order_by("producto__nombre")
        )
    pagina, consulta = paginar(request, filas)
    contexto = {"punto": punto, "puntos": puntos, "pagina": pagina, "consulta": consulta}
    return render(request, "puntoventa/existencias.html", contexto)
