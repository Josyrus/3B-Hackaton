from apps.processing.tasks import ping
from config.celery import app


def test_ping_task_runs_eagerly():
    assert ping.delay().get() == "pong"


def test_task_is_registered_with_explicit_name():
    assert "processing.ping" in app.tasks


def test_celery_is_configured_safely_and_reproducibly():
    conf = app.conf
    assert conf.task_serializer == "json"
    assert list(conf.accept_content) == ["json"]
    assert conf.task_acks_late is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_default_queue == "expedientes"
    assert conf.task_time_limit > conf.task_soft_time_limit
