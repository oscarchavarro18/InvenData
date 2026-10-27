from django.urls import path

from . import views

app_name = "puntoventa"

urlpatterns = [
    path("existencias/", views.existencias, name="existencias"),
]
