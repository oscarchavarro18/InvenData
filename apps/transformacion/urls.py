from django.urls import path

from . import views

app_name = "transformacion"

urlpatterns = [
    path("", views.orden_lista, name="orden_lista"),
    path("nueva/<int:lote_id>/<int:ubicacion_id>/", views.orden_crear, name="orden_crear"),
    path("<int:pk>/", views.orden_detalle, name="orden_detalle"),
    path("<int:pk>/editar/", views.orden_editar, name="orden_editar"),
    path("<int:pk>/eliminar/", views.orden_eliminar, name="orden_eliminar"),
    path("<int:pk>/confirmar/", views.orden_confirmar, name="orden_confirmar"),
]
