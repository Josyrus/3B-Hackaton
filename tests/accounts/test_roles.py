import pytest
from django.contrib.auth.models import AnonymousUser, Group

from apps.accounts.roles import Role, get_user_roles, user_has_role


@pytest.mark.django_db
def test_role_groups_are_created_by_migration():
    assert set(Group.objects.values_list("name", flat=True)) >= {r.value for r in Role}


def test_anonymous_has_no_roles():
    assert get_user_roles(AnonymousUser()) == frozenset()


def test_user_roles_follow_groups(make_user):
    user = make_user(Role.ANALISTA)
    assert get_user_roles(user) == {Role.ANALISTA}
    assert user_has_role(user, Role.ANALISTA, Role.COORDINADOR)
    assert not user_has_role(user, Role.ADMIN_TECNICO)


def test_unrelated_groups_are_ignored(make_user):
    user = make_user()
    user.groups.add(Group.objects.create(name="otro"))
    assert get_user_roles(user) == frozenset()


def test_superuser_has_every_role(make_user):
    user = make_user(is_superuser=True)
    assert get_user_roles(user) == frozenset(Role)


def test_inactive_user_has_no_roles(make_user):
    user = make_user(Role.ADMIN_TECNICO, is_active=False)
    assert get_user_roles(user) == frozenset()
