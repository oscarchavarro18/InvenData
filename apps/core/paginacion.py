"""Paginación sencilla para los listados."""

from django.core.paginator import Paginator

POR_PAGINA = 20


def paginar(request, consulta, por_pagina=POR_PAGINA):
    """Devuelve (página, filtros): la página pedida y los demás parámetros de la URL.

    Los filtros se devuelven ya codificados para que los enlaces «Anterior/Siguiente»
    conserven la búsqueda.
    """
    pagina = Paginator(consulta, por_pagina).get_page(request.GET.get("pagina"))
    filtros = request.GET.copy()
    filtros.pop("pagina", None)
    return pagina, filtros.urlencode()
