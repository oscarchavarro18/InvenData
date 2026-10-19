from django.urls import path

from . import views

app_name = "recepcion"

urlpatterns = [
    path("", views.documento_lista, name="documento_lista"),
    path("nuevo/", views.documento_crear, name="documento_crear"),
    path("<int:pk>/", views.documento_detalle, name="documento_detalle"),
    path("<int:pk>/lineas/agregar/", views.linea_agregar, name="linea_agregar"),
    path("lineas/<int:pk>/eliminar/", views.linea_eliminar, name="linea_eliminar"),
]
