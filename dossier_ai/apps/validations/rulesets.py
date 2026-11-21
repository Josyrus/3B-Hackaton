"""Acceso a la configuración activa: última versión en BD o, si no hay, el archivo por defecto."""
from __future__ import annotations

from core.rules import RuleSet, load_default_ruleset, parse_ruleset
from .models import RuleSetVersion


def active_ruleset() -> tuple[RuleSet, str]:
    rv = RuleSetVersion.objects.first()
    if rv is None:
        rs = load_default_ruleset()
        return rs, rs.version
    return parse_ruleset(rv.yaml_text), f"{rv.version}#{rv.pk}"
