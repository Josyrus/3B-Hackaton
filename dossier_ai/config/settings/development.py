from .base import *  # noqa: F401,F403

DEBUG = True
CELERY_TASK_ALWAYS_EAGER = env("CELERY_EAGER", "0") == "1"  # noqa: F405
