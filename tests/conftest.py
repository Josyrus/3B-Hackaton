"""Fixtures compartidas."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User

from apps.accounts.roles import Role

PASSWORD = "contrasena-segura-123"


@pytest.fixture(autouse=True)
def _isolated_private_storage(settings, tmp_path: Path) -> None:
    """Cada prueba usa su propia raíz de almacenamiento privado."""
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "private"


@pytest.fixture
def make_user(db) -> Callable[..., User]:
    def _make(role: Role | None = None, username: str = "usuario", **extra) -> User:
        user = User.objects.create_user(username, password=PASSWORD, **extra)
        if role is not None:
            user.groups.add(Group.objects.get(name=role.value))
        return user

    return _make
