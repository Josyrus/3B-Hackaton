from django.urls import path
from . import views

urlpatterns = [path("expedientes/<int:pk>/exportar/<str:fmt>/", views.export, name="export")]
