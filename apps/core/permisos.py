"""Control de acceso por perfil (RF-02).

Cada decorador exige sesión iniciada; si la persona no tiene el perfil necesario responde 403.
Leer es abierto a todo usuario con sesión, salvo la bodega, que el administrador de punto de
venta no ve (RN-06); las acciones que cambian datos exigen perfil.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def _exigir(comprobar):
    def decorador(vista):
        @wraps(vista)
        @login_required
        def envuelta(request, *args, **kwargs):
            if not comprobar(request.user):
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return envuelta

    return decorador


solo_gerente = _exigir(lambda usuario: usuario.es_gerente)
operador_de_recepcion = _exigir(lambda usuario: usuario.puede_operar_recepcion)
acceso_bodega = _exigir(lambda usuario: usuario.ve_bodega)
operador_de_bodega = _exigir(lambda usuario: usuario.puede_operar_bodega)
