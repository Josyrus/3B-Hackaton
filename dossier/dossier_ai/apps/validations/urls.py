from django.urls import path
from . import views

urlpatterns = [path("", views.config_home, name="config_home")]
