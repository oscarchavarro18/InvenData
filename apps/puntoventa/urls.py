from django.urls import path

from . import views

app_name = "puntoventa"

urlpatterns = [
    path("existencias/", views.existencias, name="existencias"),
    path("historial/", views.historial, name="historial"),
    path("ventas/", views.venta_lista, name="venta_lista"),
    path("ventas/<str:tipo>/nueva/", views.venta_nueva, name="venta_nueva"),
    path("ventas/<str:tipo>/<int:pk>/", views.venta_detalle, name="venta_detalle"),
]
