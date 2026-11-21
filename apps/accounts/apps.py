"""Configuración de la app accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Roles, permisos y vistas de autenticación."""

    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Cuentas y roles"
