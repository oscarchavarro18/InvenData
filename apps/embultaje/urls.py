from django.urls import path

from . import views

app_name = "embultaje"

urlpatterns = [
    path("", views.documento_lista, name="documento_lista"),
    path("<int:pk>/", views.documento_detalle, name="documento_detalle"),
    path("nuevo/<int:lote_id>/<int:ubicacion_id>/", views.registro_crear, name="registro_crear"),
    path("registros/<int:pk>/", views.registro_detalle, name="registro_detalle"),
    path("lotes/<int:lote_id>/cerrar/", views.lote_cerrar, name="lote_cerrar"),
    path("pedidos/", views.pedido_lista, name="pedido_lista"),
    path("pedidos/nuevo/", views.pedido_crear, name="pedido_crear"),
    path("pedidos/<int:pk>/", views.pedido_detalle, name="pedido_detalle"),
    path("pedidos/<int:pk>/lineas/agregar/", views.linea_agregar, name="linea_agregar"),
    path("pedidos/<int:pk>/alistar/", views.pedido_alistar, name="pedido_alistar"),
    path("pedidos/<int:pk>/anular/", views.pedido_anular, name="pedido_anular"),
    path("pedidos/lineas/<int:pk>/quitar/", views.linea_quitar, name="linea_quitar"),
    path("pedidos/lineas/<int:pk>/fifo/", views.linea_sugerir, name="linea_sugerir"),
    path("pedidos/lineas/<int:pk>/asignar/", views.linea_asignar, name="linea_asignar"),
    path(
        "pedidos/alistamientos/<int:pk>/quitar/",
        views.alistamiento_quitar,
        name="alistamiento_quitar",
    ),
]
