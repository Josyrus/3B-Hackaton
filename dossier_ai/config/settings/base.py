import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Variable de entorno requerida: {name}")
    return v


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = False
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts", "apps.dossiers", "apps.documents", "apps.processing", "apps.validations",
    "apps.findings", "apps.reports", "apps.audit",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages"]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": dj_database_url.parse(env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"), conn_max_age=60)}
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"}]
LOGIN_URL, LOGIN_REDIRECT_URL, LOGOUT_REDIRECT_URL = "login", "dashboard", "login"
LANGUAGE_CODE, TIME_ZONE, USE_TZ = "es-mx", "America/Mexico_City", True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
X_FRAME_OPTIONS = "SAMEORIGIN"  # el visor de PDF propio se incrusta en iframe del mismo origen

# Almacenamiento PRIVADO: fuera de STATIC/MEDIA públicos; solo accesible vía vistas autenticadas.
PRIVATE_STORAGE_ROOT = Path(env("PRIVATE_STORAGE_ROOT", str(BASE_DIR / "private_storage")))
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "50"))
MAX_ZIP_ENTRIES = int(env("MAX_ZIP_ENTRIES", "50"))
MAX_ZIP_UNCOMPRESSED_MB = int(env("MAX_ZIP_UNCOMPRESSED_MB", "200"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_ALWAYS_EAGER = False

# Procesamiento local: ningún dato sale a servicios externos salvo autorización explícita del comité.
OCR_BACKEND = env("OCR_BACKEND", "none")            # none | tesseract
EXTRACTOR_BACKEND = env("EXTRACTOR_BACKEND", "labels")  # labels | llm (LLM local vía Ollama)
LLM_MODEL = env("LLM_MODEL", "llama3.1:8b")
LLM_BASE_URL = env("LLM_BASE_URL", "http://localhost:11434")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "handlers": {"console": {"class": "logging.StreamHandler"}},
           "root": {"handlers": ["console"], "level": "INFO"}}  # Nunca se registra contenido documental
