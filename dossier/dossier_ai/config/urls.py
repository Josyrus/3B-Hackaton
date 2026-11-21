from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("api/", include("apps.dossiers.api_urls")),
    path("config/", include("apps.validations.urls")),
    path("", include("apps.dossiers.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.reports.urls")),
]
