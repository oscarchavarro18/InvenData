from django.urls import path

from . import views

app_name = "recepcion"

urlpatterns = [
    path("", views.documento_lista, name="documento_lista"),
    path("<int:pk>/", views.documento_detalle, name="documento_detalle"),
]
