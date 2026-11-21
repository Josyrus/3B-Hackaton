"""Configuración para desarrollo local."""

from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-insecure-key-never-use-in-production"  # noqa: F405
ALLOWED_HOSTS = ALLOWED_HOSTS or ["localhost", "127.0.0.1", "[::1]"]  # noqa: F405
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
