from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("", views.existencias, name="existencias"),
    path("lotes/<int:pk>/", views.lote_detalle, name="lote_detalle"),
    path("trasladar/<int:lote_id>/<int:ubicacion_id>/", views.trasladar, name="trasladar"),
]
