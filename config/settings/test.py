"""Configuración para pytest: sin servicios externos, rápida y aislada."""

import tempfile
from pathlib import Path

from .base import *  # noqa: F403

SECRET_KEY = "test-secret-key-only-for-automated-tests-0123456789abcdef"  # noqa: S105
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

# SQLite en memoria: las pruebas no requieren PostgreSQL. La integración real
# con PostgreSQL se verifica con DJANGO_SETTINGS_MODULE=config.settings.development.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PRIVATE_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="expedientes-test-"))
