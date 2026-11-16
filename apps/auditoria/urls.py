from django.urls import path

from . import views

app_name = "auditoria"

urlpatterns = [
    path("", views.auditoria_lista, name="auditoria_lista"),
    path("<int:pk>/", views.auditoria_detalle, name="auditoria_detalle"),
]
