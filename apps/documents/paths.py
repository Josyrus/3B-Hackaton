"""Generación segura de rutas de almacenamiento.

El nombre original del archivo del usuario NUNCA forma parte de la ruta: se
guarda como metadato y la ruta se construye solo con UUID validados.
"""

from __future__ import annotations

from uuid import UUID

ALLOWED_EXTENSIONS = frozenset({"pdf", "zip"})


def document_storage_path(
    dossier_id: UUID | str, document_id: UUID | str, extension: str = "pdf"
) -> str:
    """Devuelve ``dossiers/<dossier_uuid>/<document_uuid>.<ext>``.

    Raises:
        ValueError: si un identificador no es un UUID válido o la extensión
            no está permitida.
    """
    dossier = UUID(str(dossier_id))
    document = UUID(str(document_id))
    ext = extension.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Extensión no permitida: {extension!r}")
    return f"dossiers/{dossier}/{document}.{ext}"
