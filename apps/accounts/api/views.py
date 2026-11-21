"""Endpoints de API de accounts."""

from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import get_user_roles


class MeView(APIView):
    """Datos mínimos del usuario autenticado y sus roles."""

    def get(self, request: Request) -> Response:
        user = request.user
        return Response(
            {
                "username": user.get_username(),
                "roles": sorted(role.value for role in get_user_roles(user)),
            }
        )
