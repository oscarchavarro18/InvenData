from django.urls import path

from . import views

app_name = "levantamiento"

urlpatterns = [
    path("", views.levantamiento_lista, name="levantamiento_lista"),
    path("nuevo/<int:ubicacion_id>/", views.levantamiento_crear, name="levantamiento_crear"),
    path("<int:pk>/", views.levantamiento_detalle, name="levantamiento_detalle"),
    path("<int:pk>/agregar/", views.linea_agregar, name="linea_agregar"),
    path("<int:pk>/aprobar/", views.levantamiento_aprobar, name="levantamiento_aprobar"),
    path("lineas/<str:tipo>/<int:pk>/quitar/", views.linea_quitar, name="linea_quitar"),
]
