from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("expedientes/", views.dossier_list, name="list"),
    path("expedientes/nuevo/", views.upload, name="upload"),
    path("expedientes/<int:pk>/", views.detail, name="detail"),
    path("expedientes/<int:pk>/progreso/", views.progress, name="progress"),
    path("expedientes/<int:pk>/progreso.json", views.progress_json, name="progress_json"),
    path("expedientes/<int:pk>/reejecutar/", views.rerun, name="rerun"),
    path("documentos/<int:doc_id>/clasificacion/", views.correct_classification, name="correct_classification"),
    path("datos/<int:field_id>/corregir/", views.correct_field, name="correct_field"),
]
