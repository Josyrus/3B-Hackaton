import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.roles import Role
from apps.audit.models import AuditAction, AuditLog
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_home_requires_login(client):
    response = client.get(reverse("home"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response["Location"]


def test_login_page_renders(client):
    assert client.get(reverse("accounts:login")).status_code == 200


def test_login_success_redirects_and_shows_roles(client, make_user):
    make_user(Role.ANALISTA, username="ana")
    response = client.post(reverse("accounts:login"), {"username": "ana", "password": PASSWORD})
    assert response.status_code == 302
    assert response["Location"] == reverse("home")
    assert "analista" in client.get(reverse("home")).content.decode()


def test_login_failure_shows_error_and_is_audited(client, make_user):
    make_user(username="ana")
    response = client.post(reverse("accounts:login"), {"username": "ana", "password": "mala"})
    assert response.status_code == 200
    entry = AuditLog.objects.get(action=AuditAction.LOGIN_FAILED)
    assert entry.metadata == {"username": "ana"}
    assert "mala" not in str(entry.metadata)


def test_logout_requires_post(client, make_user):
    client.force_login(make_user())
    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert client.get(reverse("home")).status_code == 302


def test_login_enforces_csrf(make_user):
    make_user(username="ana")
    strict = Client(enforce_csrf_checks=True)
    response = strict.post(reverse("accounts:login"), {"username": "ana", "password": PASSWORD})
    assert response.status_code == 403
