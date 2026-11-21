"""Chequeos de sistema de Django para la confidencialidad del almacenamiento."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.checks import Error, register


def _is_inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


@register()
def check_private_storage_location(app_configs: Any = None, **kwargs: Any) -> list[Error]:
    """Falla si el almacenamiento privado quedaría bajo un directorio servible."""
    root = Path(settings.PRIVATE_STORAGE_ROOT).resolve()
    public_dirs = [getattr(settings, "STATIC_ROOT", None), getattr(settings, "MEDIA_ROOT", None)]
    public_dirs += list(getattr(settings, "STATICFILES_DIRS", []))
    errors: list[Error] = []
    for directory in public_dirs:
        if directory and _is_inside(root, Path(directory).resolve()):
            errors.append(
                Error(
                    "PRIVATE_STORAGE_ROOT está dentro de un directorio de archivos públicos.",
                    hint=f"Muévalo fuera de {directory}.",
                    id="documents.E001",
                )
            )
    return errors
