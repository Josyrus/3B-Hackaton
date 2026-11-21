"""Rutas raíz del proyecto."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import HomeView
from apps.core.views import health

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", HomeView.as_view(), name="home"),
    path("cuenta/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.accounts.api.urls")),
    path("health/", health, name="health"),
]
