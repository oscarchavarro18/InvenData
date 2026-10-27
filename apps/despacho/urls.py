from django.urls import path

from . import views

app_name = "despacho"

urlpatterns = [
    path("", views.despacho_lista, name="despacho_lista"),
    path("pedidos/<int:pedido_id>/", views.despacho_crear, name="despacho_crear"),
    path("<int:pk>/", views.despacho_detalle, name="despacho_detalle"),
    path("<int:pk>/entrega/", views.entrega_registrar, name="entrega_registrar"),
    path("<int:pk>/evidencias/<int:evidencia_pk>/", views.evidencia_ver, name="evidencia_ver"),
    path("traslados/", views.traslado_lista, name="traslado_lista"),
    path("traslados/nuevo/", views.traslado_crear, name="traslado_crear"),
    path("traslados/<int:pk>/", views.traslado_detalle, name="traslado_detalle"),
    path("traslados/<int:pk>/decidir/", views.traslado_decidir, name="traslado_decidir"),
    path("traslados/<int:pk>/observar/", views.traslado_observar, name="traslado_observar"),
]
