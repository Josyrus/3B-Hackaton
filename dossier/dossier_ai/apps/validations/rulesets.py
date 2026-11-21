"""Acceso a la configuración activa: última versión en BD o, si no hay, el archivo por defecto (o RULESET_FILE)."""
from __future__ import annotations

from django.conf import settings

from core.rules import RuleSet, load_default_ruleset, load_ruleset_file, parse_ruleset
from .models import RuleSetVersion


def active_ruleset() -> tuple[RuleSet, str]:
    rv = RuleSetVersion.objects.first()
    if rv is None:
        rs = load_ruleset_file(settings.RULESET_FILE) if getattr(settings, "RULESET_FILE", "") else load_default_ruleset()
        return rs, rs.version
    return parse_ruleset(rv.yaml_text), f"{rv.version}#{rv.pk}"
