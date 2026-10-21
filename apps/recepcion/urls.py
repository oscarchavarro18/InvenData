from django.urls import path

from . import views

app_name = "recepcion"

urlpatterns = [
    path("", views.documento_lista, name="documento_lista"),
    path("nuevo/", views.documento_crear, name="documento_crear"),
    path("<int:pk>/", views.documento_detalle, name="documento_detalle"),
    path("<int:pk>/cerrar/", views.documento_cerrar, name="documento_cerrar"),
    path("<int:pk>/lineas/agregar/", views.linea_agregar, name="linea_agregar"),
    path("lineas/<int:pk>/eliminar/", views.linea_eliminar, name="linea_eliminar"),
    path("lineas/<int:pk>/lotes/nuevo/", views.lote_crear, name="lote_crear"),
    path("lotes/<int:pk>/eliminar/", views.lote_eliminar, name="lote_eliminar"),
    path("lotes/<int:pk>/pesadas/nueva/", views.pesada_registrar, name="pesada_registrar"),
]
