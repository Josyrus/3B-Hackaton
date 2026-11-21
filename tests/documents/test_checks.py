from apps.documents.checks import check_private_storage_location


def test_default_location_is_valid():
    assert check_private_storage_location() == []


def test_root_inside_static_root_is_an_error(settings, tmp_path):
    settings.STATIC_ROOT = tmp_path / "static"
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "static" / "docs"
    assert [e.id for e in check_private_storage_location()] == ["documents.E001"]


def test_root_equal_to_media_root_is_an_error(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "media"
    assert [e.id for e in check_private_storage_location()] == ["documents.E001"]


def test_root_inside_staticfiles_dirs_is_an_error(settings, tmp_path):
    settings.STATICFILES_DIRS = [tmp_path / "assets"]
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "assets" / "private"
    assert [e.id for e in check_private_storage_location()] == ["documents.E001"]
