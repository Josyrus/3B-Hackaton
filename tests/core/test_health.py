from unittest.mock import MagicMock, patch

import pytest
import redis
from django.db import OperationalError
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_health_ok_with_eager_celery(client):
    response = client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "broker": "skipped"}}


def test_health_checks_broker_when_not_eager(client, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    with patch("apps.core.views.redis.Redis.from_url", return_value=MagicMock()) as from_url:
        response = client.get(reverse("health"))
    assert response.status_code == 200
    assert response.json()["checks"]["broker"] == "ok"
    from_url.return_value.ping.assert_called_once()


def test_health_degraded_when_broker_down_without_leaking_details(client, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    boom = MagicMock()
    boom.ping.side_effect = redis.ConnectionError("secret-host:6379 refused")
    with patch("apps.core.views.redis.Redis.from_url", return_value=boom):
        response = client.get(reverse("health"))
    assert response.status_code == 503
    assert "secret-host" not in response.content.decode()
    assert response.json()["checks"]["broker"] == "error"


def test_health_degraded_when_database_down(client):
    with patch("apps.core.views.connection") as conn:
        conn.cursor.side_effect = OperationalError("db down")
        response = client.get(reverse("health"))
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"


def test_health_only_allows_get(client):
    assert client.post(reverse("health")).status_code == 405
