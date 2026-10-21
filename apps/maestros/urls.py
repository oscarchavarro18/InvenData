from django.urls import path

from . import views

app_name = "maestros"

urlpatterns = [
    path("productos/", views.producto_lista, name="producto_lista"),
    path("productos/nuevo/", views.producto_crear, name="producto_crear"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/embalajes/nuevo/", views.embalaje_crear, name="embalaje_crear"),
    path("configuracion/embalajes/<int:pk>/editar/", views.embalaje_editar, name="embalaje_editar"),
    path("configuracion/embalajes/<int:pk>/estado/", views.embalaje_estado, name="embalaje_estado"),
]
