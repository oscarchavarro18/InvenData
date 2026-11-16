from django.urls import path

from apps.reportes import views

app_name = "reportes"

urlpatterns = [
    path("", views.indice, name="indice"),
    path("informe/", views.informe, name="informe"),
    path("indicadores/", views.indicadores, name="indicadores"),
    path("trazabilidad/", views.trazabilidad, name="trazabilidad"),
    path("mermas/", views.mermas, name="mermas"),
    path("existencias-bodega/", views.existencias_bodega, name="existencias_bodega"),
    path("existencias-pdv/", views.existencias_pdv, name="existencias_pdv"),
    path("por-vencer/", views.por_vencer, name="por_vencer"),
    path("ventas/", views.ventas, name="ventas"),
    path("correcciones/", views.correcciones, name="correcciones"),
]
