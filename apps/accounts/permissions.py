"""Control de acceso por roles para vistas de Django y DRF."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from rest_framework.permissions import BasePermission

from .roles import Role, user_has_role


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Exige sesión iniciada y al menos uno de ``required_roles``.

    Un anónimo es redirigido al login; un usuario autenticado sin el rol
    recibe 403.
    """

    request: HttpRequest
    required_roles: tuple[Role, ...] = ()

    def test_func(self) -> bool:
        if not self.required_roles:
            raise ImproperlyConfigured(f"{type(self).__name__} debe definir required_roles.")
        return user_has_role(self.request.user, *self.required_roles)


def roles_required(*roles: Role) -> type[BasePermission]:
    """Crea una clase de permiso DRF que exige alguno de los roles indicados."""
    if not roles:
        raise ImproperlyConfigured("roles_required necesita al menos un rol.")

    class HasRole(BasePermission):
        message = "No tiene el rol necesario para esta operación."

        def has_permission(self, request, view) -> bool:
            return user_has_role(request.user, *roles)

    return HasRole
