import os
import stat
from uuid import uuid4

import pytest
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.base import ContentFile

from apps.documents.paths import document_storage_path
from apps.documents.storage import get_private_storage


def test_saved_file_and_directory_are_private(settings):
    storage = get_private_storage()
    name = storage.save(document_storage_path(uuid4(), uuid4()), ContentFile(b"%PDF-1.4"))
    path = storage.path(name)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) & 0o077 == 0
    assert str(path).startswith(str(settings.PRIVATE_STORAGE_ROOT))


def test_storage_has_no_public_url():
    with pytest.raises(PermissionError):
        get_private_storage().url("dossiers/x.pdf")


@pytest.mark.parametrize("name", ["../escape.pdf", "../../etc/passwd", "/etc/passwd"])
def test_path_traversal_is_rejected(name):
    storage = get_private_storage()
    with pytest.raises(SuspiciousFileOperation):
        storage.save(name, ContentFile(b"x"))


def test_default_storage_is_private_backend():
    from django.core.files.storage import default_storage

    assert default_storage.__class__.__name__ == "PrivateFileSystemStorage"


def test_storage_path_uses_only_validated_uuids():
    d, f = uuid4(), uuid4()
    assert document_storage_path(d, f) == f"dossiers/{d}/{f}.pdf"
    assert document_storage_path(str(d), str(f), "ZIP").endswith(".zip")


@pytest.mark.parametrize(
    ("dossier", "document", "ext"),
    [
        ("../../etc", str(uuid4()), "pdf"),
        (str(uuid4()), "no-es-uuid", "pdf"),
        (str(uuid4()), str(uuid4()), "exe"),
        (str(uuid4()), str(uuid4()), "pdf/../x"),
    ],
)
def test_storage_path_rejects_malicious_input(dossier, document, ext):
    with pytest.raises(ValueError, match=r"UUID|badly formed|Extensión"):
        document_storage_path(dossier, document, ext)
