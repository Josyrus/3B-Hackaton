import pytest
from django.urls import reverse

from apps.accounts.roles import Role

pytestmark = pytest.mark.django_db


def test_me_requires_authentication(client):
    assert client.get(reverse("api-me")).status_code == 403


def test_me_returns_username_and_roles(client, make_user):
    client.force_login(make_user(Role.COORDINADOR, username="coord"))
    response = client.get(reverse("api-me"))
    assert response.status_code == 200
    assert response.json() == {"username": "coord", "roles": ["coordinador"]}
