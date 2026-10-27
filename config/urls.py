from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.accounts.forms import IngresoForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(authentication_form=IngresoForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("recepcion/", include("apps.recepcion.urls")),
    path("inventario/", include("apps.inventario.urls")),
    path("transformacion/", include("apps.transformacion.urls")),
    path("embultaje/", include("apps.embultaje.urls")),
    path("despacho/", include("apps.despacho.urls")),
    path("punto-venta/", include("apps.puntoventa.urls")),
    path("", include("apps.maestros.urls")),
    path("", include("apps.core.urls")),
]
