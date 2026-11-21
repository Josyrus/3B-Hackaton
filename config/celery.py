"""Aplicación Celery del proyecto.

La configuración se lee de los settings de Django con el prefijo ``CELERY_``.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("expedientes")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
