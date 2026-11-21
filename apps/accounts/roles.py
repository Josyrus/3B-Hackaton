"""Roles del sistema y utilidades para consultarlos.

Los roles se implementan con grupos de Django cuyo nombre es el valor del rol.
Los grupos los crea la migración ``0001_create_role_groups``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User


class Role(StrEnum):
    """Roles de negocio definidos en el documento de especificación."""

    ANALISTA = "analista"
    COORDINADOR = "coordinador"
    ADMIN_TECNICO = "admin_tecnico"


def get_user_roles(user: User | AnonymousUser) -> frozenset[Role]:
    """Devuelve los roles del usuario.

    Un superusuario activo tiene todos los roles. Un usuario anónimo o inactivo
    no tiene ninguno. Grupos ajenos al catálogo de roles se ignoran.
    """
    if not user.is_authenticated or not user.is_active:
        return frozenset()
    if user.is_superuser:
        return frozenset(Role)
    names = user.groups.values_list("name", flat=True)
    valid = {role.value: role for role in Role}
    return frozenset(valid[name] for name in names if name in valid)


def user_has_role(user: User | AnonymousUser, *roles: Role) -> bool:
    """Indica si el usuario tiene al menos uno de los roles indicados."""
    return bool(get_user_roles(user) & set(roles))
