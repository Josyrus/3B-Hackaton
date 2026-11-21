"""Configuración base compartida por todos los entornos.

Todo valor sensible o dependiente del entorno se lee de variables de entorno
(o de un archivo ``.env`` local que nunca se versiona).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    environ.Env.read_env(_env_file)

# --- Núcleo -----------------------------------------------------------------
# Sin valor por defecto: development/test definen el suyo y production
# exige uno válido (ver production.py).
SECRET_KEY = env.str("DJANGO_SECRET_KEY", default="")
DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])
ADMIN_URL = env.str("DJANGO_ADMIN_URL", default="admin/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.audit",
    "apps.core",
    "apps.documents",
    "apps.processing",
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
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Base de datos ----------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://expedientes:expedientes@localhost:5432/expedientes",
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env.str("REDIS_CACHE_URL", default="redis://localhost:6379/2"),
    }
}

# --- Autenticación y sesiones ----------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE_SECONDS", default=8 * 60 * 60)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"

# SAMEORIGIN: el visor de evidencia (Fase 6) incrusta PDFs propios en un iframe.
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# --- Internacionalización ---------------------------------------------------
LANGUAGE_CODE = "es-mx"
TIME_ZONE = env.str("TIME_ZONE", default="America/Mexico_City")
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos y almacenamiento privado ---------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Los documentos NUNCA viven bajo STATIC_ROOT/MEDIA_ROOT ni tienen URL pública.
# No se define MEDIA_URL a propósito. Ver apps/documents/storage.py.
PRIVATE_STORAGE_ROOT = Path(
    env.str("PRIVATE_STORAGE_ROOT", default=str(BASE_DIR / "private_storage"))
)
STORAGES = {
    "default": {"BACKEND": "apps.documents.storage.PrivateFileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --- Límites de carga (se aplican en la Fase 3) ----------------------------
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # por encima, usa archivo temporal
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # cuerpo sin archivos
MAX_PDF_SIZE_MB = env.int("MAX_PDF_SIZE_MB", default=50)
MAX_ZIP_SIZE_MB = env.int("MAX_ZIP_SIZE_MB", default=200)
MAX_ZIP_ENTRIES = env.int("MAX_ZIP_ENTRIES", default=100)
MAX_ZIP_UNCOMPRESSED_MB = env.int("MAX_ZIP_UNCOMPRESSED_MB", default=500)
MAX_ZIP_COMPRESSION_RATIO = env.int("MAX_ZIP_COMPRESSION_RATIO", default=100)

# --- Confidencialidad -------------------------------------------------------
# Política RNF-05: los documentos se procesan solo con proveedores locales.
# Los adaptadores de LLM/OCR (Fase 3-4) deben negarse a usar un proveedor
# remoto mientras este valor sea False.
ALLOW_EXTERNAL_PROVIDERS = env.bool("ALLOW_EXTERNAL_PROVIDERS", default=False)

# --- Procesamiento asíncrono (Celery) --------------------------------------
ANALYSIS_TIME_BUDGET_SECONDS = env.int("ANALYSIS_TIME_BUDGET_SECONDS", default=300)

CELERY_BROKER_URL = env.str("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env.str("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_DEFAULT_QUEUE = "expedientes"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SOFT_TIME_LIMIT = ANALYSIS_TIME_BUDGET_SECONDS * 2
CELERY_TASK_TIME_LIMIT = ANALYSIS_TIME_BUDGET_SECONDS * 2 + 60
CELERY_RESULT_EXPIRES = 60 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

# --- API REST ---------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "300/min"},
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

# --- Logging ----------------------------------------------------------------
# Regla del proyecto: los logs registran IDs y métricas, nunca texto documental.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}
