"""Pruebas de endurecimiento de configuración."""

import runpy
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

GOOD_KEY = "k" * 60


def _load_production(monkeypatch, **env):
    for name in ("DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    # Fuerza a base.py a releer el entorno.
    monkeypatch.delitem(sys.modules, "config.settings.base", raising=False)
    monkeypatch.delitem(sys.modules, "config.settings.production", raising=False)
    return runpy.run_module("config.settings.production")


def test_production_requires_secret_key(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        _load_production(monkeypatch, DJANGO_ALLOWED_HOSTS="app.example.com")


def test_production_rejects_short_secret_key(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        _load_production(monkeypatch, DJANGO_SECRET_KEY="corta", DJANGO_ALLOWED_HOSTS="a.com")


def test_production_requires_allowed_hosts(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        _load_production(monkeypatch, DJANGO_SECRET_KEY=GOOD_KEY)


def test_production_hardening(monkeypatch):
    conf = _load_production(
        monkeypatch, DJANGO_SECRET_KEY=GOOD_KEY, DJANGO_ALLOWED_HOSTS="app.example.com"
    )
    assert conf["DEBUG"] is False
    assert conf["SESSION_COOKIE_SECURE"] is True
    assert conf["CSRF_COOKIE_SECURE"] is True
    assert conf["SECURE_SSL_REDIRECT"] is True
    assert conf["SECURE_HSTS_SECONDS"] > 0
    assert conf["ALLOWED_HOSTS"] == ["app.example.com"]


def test_confidentiality_defaults(settings):
    assert settings.ALLOW_EXTERNAL_PROVIDERS is False
    assert settings.MEDIA_ROOT == ""  # no hay carpeta media pública
    assert (
        settings.STORAGES["default"]["BACKEND"] == "apps.documents.storage.PrivateFileSystemStorage"
    )
    assert settings.SESSION_COOKIE_HTTPONLY is True
