"""Almacenamiento privado de documentos.

Garantías:
- Ubicación fuera de static/media (ver ``checks.py``).
- Sin URL pública: ``url()`` siempre falla. El acceso a un PDF se hace por una
  vista autenticada que lo sirve (Fase 6) y registra auditoría.
- Permisos de sistema de archivos restrictivos (archivos 0600, directorios 0700).
- ``FileSystemStorage`` rechaza rutas fuera de la raíz (path traversal).
"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Any

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateFileSystemStorage(FileSystemStorage):
    """Storage local sin URL pública, con la raíz tomada de ``PRIVATE_STORAGE_ROOT``."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("file_permissions_mode", 0o600)
        kwargs.setdefault("directory_permissions_mode", 0o700)
        super().__init__(**kwargs)

    @cached_property
    def base_location(self) -> str:
        return os.fspath(settings.PRIVATE_STORAGE_ROOT)

    def url(self, name: str | None) -> str:
        raise PermissionError("Los documentos privados no tienen URL pública.")


def get_private_storage() -> PrivateFileSystemStorage:
    """Crea una instancia del almacenamiento privado."""
    return PrivateFileSystemStorage()
