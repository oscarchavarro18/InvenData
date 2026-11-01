from django.urls import path

from . import views

app_name = "conteo"

urlpatterns = [
    path("", views.conteo_lista, name="conteo_lista"),
    path("nuevo/", views.conteo_nuevo, name="conteo_nuevo"),
    path("<int:pk>/", views.conteo_detalle, name="conteo_detalle"),
    path(
        "ajustes/bodega/<int:lote_id>/<int:ubicacion_id>/",
        views.ajuste_bodega,
        name="ajuste_bodega",
    ),
    path("ajustes/punto-venta/", views.ajuste_pdv, name="ajuste_pdv"),
    path("reversos/bodega/<int:movimiento_id>/", views.reverso_bodega, name="reverso_bodega"),
    path("reversos/punto-venta/<int:movimiento_id>/", views.reverso_pdv, name="reverso_pdv"),
]
