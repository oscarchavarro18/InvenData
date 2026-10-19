from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.accounts.forms import IngresoForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(authentication_form=IngresoForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("recepcion/", include("apps.recepcion.urls")),
    path("", include("apps.core.urls")),
]
