from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.usuario_lista, name="usuario_lista"),
    path("nuevo/", views.usuario_crear, name="usuario_crear"),
    path("<int:pk>/editar/", views.usuario_editar, name="usuario_editar"),
    path("<int:pk>/estado/", views.usuario_estado, name="usuario_estado"),
    path("<int:pk>/contrasena/", views.usuario_clave, name="usuario_clave"),
]
