"""Rutas de autenticación."""

from django.contrib.auth import views as auth_views
from django.urls import path

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    # En Django 5 el logout solo acepta POST (protegido por CSRF).
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
