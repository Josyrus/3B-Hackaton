import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpResponse
from django.views import View
from rest_framework.test import APIRequestFactory

from apps.accounts.permissions import RoleRequiredMixin, roles_required
from apps.accounts.roles import Role


class AdminOnlyView(RoleRequiredMixin, View):
    required_roles = (Role.ADMIN_TECNICO,)

    def get(self, request):
        return HttpResponse("ok")


class MisconfiguredView(RoleRequiredMixin, View):
    def get(self, request):
        return HttpResponse("ok")


def _get(rf, user):
    request = rf.get("/x/")
    request.user = user
    return request


def test_anonymous_is_redirected_to_login(rf):
    response = AdminOnlyView.as_view()(_get(rf, AnonymousUser()))
    assert response.status_code == 302
    assert "/cuenta/login/" in response["Location"]


def test_wrong_role_gets_403(rf, make_user):
    with pytest.raises(PermissionDenied):
        AdminOnlyView.as_view()(_get(rf, make_user(Role.ANALISTA)))


def test_right_role_gets_200(rf, make_user):
    response = AdminOnlyView.as_view()(_get(rf, make_user(Role.ADMIN_TECNICO)))
    assert response.status_code == 200


def test_view_without_roles_is_misconfigured(rf, make_user):
    with pytest.raises(ImproperlyConfigured):
        MisconfiguredView.as_view()(_get(rf, make_user(Role.ADMIN_TECNICO)))


def test_drf_permission(make_user):
    permission = roles_required(Role.COORDINADOR)()
    request = APIRequestFactory().get("/")
    request.user = make_user(Role.COORDINADOR)
    assert permission.has_permission(request, None)
    request.user = make_user(Role.ANALISTA, username="otro")
    assert not permission.has_permission(request, None)


def test_drf_permission_requires_roles():
    with pytest.raises(ImproperlyConfigured):
        roles_required()
