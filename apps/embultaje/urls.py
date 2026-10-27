from django.urls import path

from . import views

app_name = "embultaje"

urlpatterns = [
    path("", views.documento_lista, name="documento_lista"),
    path("<int:pk>/", views.documento_detalle, name="documento_detalle"),
    path("nuevo/<int:lote_id>/<int:ubicacion_id>/", views.registro_crear, name="registro_crear"),
    path("registros/<int:pk>/", views.registro_detalle, name="registro_detalle"),
    path("lotes/<int:lote_id>/cerrar/", views.lote_cerrar, name="lote_cerrar"),
]
