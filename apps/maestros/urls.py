from django.urls import path

from . import views

app_name = "maestros"

urlpatterns = [
    path("productos/", views.producto_lista, name="producto_lista"),
    path("productos/nuevo/", views.producto_crear, name="producto_crear"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
