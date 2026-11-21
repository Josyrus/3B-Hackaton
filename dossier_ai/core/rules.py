"""Carga de configuración y motor de reglas (Strategy). Las reglas viven en YAML, no en el código."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from pydantic import BaseModel, Field, ValidationError

from .contracts import DocumentType, FieldValue, Outcome, RuleOutcome, Verification
from .normalization import normalize_text, parse_date

DEFAULT_RULESET = Path(__file__).resolve().parent.parent / "rules" / "ruleset.yaml"


class Thresholds(BaseModel):
    classification_min_confidence: float = 0.8
    verdict_min_confidence: float = 0.8
    surface_tolerance_pct: float | None = None


class RuleDef(BaseModel):
    id: str
    doc_type: DocumentType
    type: str
    field: str
    provisional: bool = False
    category: str = "requisito"
    params: dict[str, Any] = Field(default_factory=dict)


class CrossSource(BaseModel):
    doc_type: DocumentType
    field: str


class CrossCheck(BaseModel):
    field: str
    kind: str
    sources: list[CrossSource]


class RuleSet(BaseModel):
    version: str
    thresholds: Thresholds = Field(default_factory=Thresholds)
    classification_keywords: dict[DocumentType, list[str]]
    schemas: dict[DocumentType, dict[str, list[str]]]
    rules: list[RuleDef]
    cross_checks: list[CrossCheck] = Field(default_factory=list)


class RuleSetError(ValueError):
    pass


def parse_ruleset(text: str) -> RuleSet:
    try:
        rs = RuleSet.model_validate(yaml.safe_load(text))
    except (yaml.YAMLError, ValidationError) as exc:
        raise RuleSetError(str(exc)) from exc
    unknown = [r.type for r in rs.rules if r.type not in STRATEGIES]
    if unknown:
        raise RuleSetError(f"Tipos de regla desconocidos: {sorted(set(unknown))}")
    return rs


def load_default_ruleset() -> RuleSet:
    return parse_ruleset(DEFAULT_RULESET.read_text(encoding="utf-8"))


# --- Strategies -------------------------------------------------------------------------

class RuleContext(BaseModel):
    reference_date: date


class RuleStrategy(Protocol):
    def __call__(self, rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]: ...


def _required_field(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is not None and fv.found:
        return Outcome.PASS, f"Campo '{rule.field}' presente."
    return Outcome.FAIL, f"Campo '{rule.field}' no encontrado en el documento."


def _date_not_expired(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, "Vigencia no encontrada."
    d = parse_date(fv.raw)
    if d is None:
        return Outcome.INDETERMINATE, "La vigencia no es una fecha interpretable."
    if d < ctx.reference_date:
        return Outcome.FAIL, f"Documento vencido el {d.isoformat()}."
    return Outcome.PASS, f"Vigente hasta {d.isoformat()}."


def _enum_match(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, f"Campo '{rule.field}' no encontrado."
    value = normalize_text(fv.raw).strip(" .")
    if value in [normalize_text(v) for v in rule.params.get("fail", [])]:
        return Outcome.FAIL, f"El documento declara: '{fv.raw}'."
    if value in [normalize_text(v) for v in rule.params.get("pass", [])]:
        return Outcome.PASS, f"El documento declara: '{fv.raw}'."
    return Outcome.INDETERMINATE, f"Valor ambiguo: '{fv.raw}'."


def _report_if_present(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is not None and fv.found and normalize_text(fv.raw) not in {"ninguna", "no aplica", "sin restricciones", "n/a"}:
        return Outcome.INDETERMINATE, f"Se declaran restricciones/condicionantes: '{fv.raw}'."
    return Outcome.PASS, "Sin restricciones declaradas."


STRATEGIES: dict[str, Callable[..., tuple[Outcome, str]]] = {
    "required_field": _required_field,
    "date_not_expired": _date_not_expired,
    "enum_match": _enum_match,
    "report_if_present": _report_if_present,
}


def evaluate_rule(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> RuleOutcome:
    """Evalúa una regla. Sin evidencia confiable, un resultado FAIL/PASS sustentado en un dato
    no verificado se degrada a INDETERMINADA (los datos no verificados no sustentan conclusiones)."""
    outcome, msg = STRATEGIES[rule.type](rule, fv, ctx)
    evidence = [fv.evidence] if fv is not None and fv.found else []
    trusted = all(e.verification.is_trusted for e in evidence)
    if evidence and not trusted:
        outcome, msg = Outcome.INDETERMINATE, f"Evidencia no verificada. ({msg})"
    return RuleOutcome(rule_id=rule.id, doc_type=rule.doc_type, outcome=outcome,
                       provisional=rule.provisional, category=rule.category, message=msg, evidence=evidence)


def pick_field(fields: list[FieldValue], doc_type: DocumentType, name: str) -> FieldValue | None:
    """Primer valor confiable encontrado; si no, el primero encontrado; si no, cualquiera."""
    cands = [f for f in fields if f.doc_type == doc_type and f.name == name]
    for pred in (lambda f: f.found and f.evidence.verification.is_trusted, lambda f: f.found, lambda f: True):
        for f in cands:
            if pred(f):
                return f
    return None


__all__ = ["RuleSet", "RuleSetError", "parse_ruleset", "load_default_ruleset", "evaluate_rule",
           "pick_field", "RuleContext", "Verification"]
