from .base import *  # noqa: F401,F403
import tempfile

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PRIVATE_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="dossier_test_"))  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
