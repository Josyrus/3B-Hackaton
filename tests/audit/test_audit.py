import pytest
from django.contrib.auth.models import Group

from apps.audit.models import AuditAction, AuditLog
from apps.audit.services import record_audit

pytestmark = pytest.mark.django_db


def test_record_audit_stores_actor_object_and_ip(rf, make_user):
    user = make_user()
    request = rf.get("/", REMOTE_ADDR="10.1.2.3")
    request.user = user
    group = Group.objects.first()
    entry = record_audit(AuditAction.DOSSIER_CREATED, request=request, obj=group, metadata={"n": 1})
    assert entry.user == user
    assert entry.ip_address == "10.1.2.3"
    assert entry.object_type == "auth.group"
    assert entry.object_id == str(group.pk)
    assert entry.metadata == {"n": 1}


def test_record_audit_ignores_x_forwarded_for(rf):
    request = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6")
    entry = record_audit(AuditAction.LOGIN_FAILED, request=request)
    assert entry.ip_address == "10.0.0.1"


def test_audit_entries_are_immutable():
    entry = record_audit(AuditAction.LOGIN)
    entry.action = AuditAction.LOGOUT
    with pytest.raises(PermissionError):
        entry.save()
    with pytest.raises(PermissionError):
        entry.delete()


def test_login_and_logout_signals_create_entries(client, make_user):
    from tests.conftest import PASSWORD

    user = make_user(username="ana")
    assert client.login(username="ana", password=PASSWORD)
    client.logout()
    actions = list(AuditLog.objects.filter(user=user).values_list("action", flat=True))
    assert AuditAction.LOGIN in actions
    assert AuditAction.LOGOUT in actions


def test_failed_login_signal_without_request(client):
    client.login(username="nadie", password="x")
    assert AuditLog.objects.filter(action=AuditAction.LOGIN_FAILED).count() == 1
