from django.urls import path

from . import views
from .catalogos import CATALOGOS

app_name = "maestros"

urlpatterns = [
    path("productos/", views.producto_lista, name="producto_lista"),
    path("productos/nuevo/", views.producto_crear, name="producto_crear"),
    path("productos/<int:pk>/editar/", views.producto_editar, name="producto_editar"),
    path("productos/<int:pk>/estado/", views.producto_estado, name="producto_estado"),
    path("administracion/", views.administracion, name="administracion"),
]

# Cada catálogo de la Administración tiene sus cuatro rutas, con nombres propios
# (maestros:ubicacion_lista, maestros:embalaje_crear, …).
for clave, catalogo in CATALOGOS.items():
    base = f"administracion/{catalogo.ruta_base}/"
    urlpatterns += [
        path(base, views.catalogo_lista, {"clave": clave}, name=f"{clave}_lista"),
        path(f"{base}nuevo/", views.catalogo_crear, {"clave": clave}, name=f"{clave}_crear"),
        path(
            f"{base}<int:pk>/editar/",
            views.catalogo_editar,
            {"clave": clave},
            name=f"{clave}_editar",
        ),
        path(
            f"{base}<int:pk>/estado/",
            views.catalogo_estado,
            {"clave": clave},
            name=f"{clave}_estado",
        ),
    ]
