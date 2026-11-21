"""Carga de configuración y motor de reglas (Strategy). Las reglas viven en archivos (YAML o JSON del comité), no en el código.

Principio anti falsos "No cumple": un dato NO localizado, NO verificado o leído por OCR dudoso produce INDETERMINADA
(→ revisión humana), nunca NO CUMPLE. Un NO CUMPLE exige dato presente, evidencia verificada y, si viene de OCR,
confianza alta y coincidencia exacta.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .contracts import DocumentType, FieldValue, Outcome, RuleOutcome, Verification
from .normalization import add_period, all_dates, normalize_text, numbers_in, parse_area_m2, parse_date, parse_period

DEFAULT_RULESET = Path(__file__).resolve().parent.parent / "rules" / "ruleset.yaml"

# Operadores del comité (reglas_comite.json) -> estrategia interna
OPERATOR_ALIASES = {
    "obligatorio": "required_field",
    "es_verdadero": "is_true",
    "mayor_que": "greater_than",
    "vigente_a_fecha_actual": "date_not_expired",
    "reportar_si_existe": "report_if_present",
}
SEVERITIES = ("critico", "relevante", "informativo")


class Thresholds(BaseModel):
    classification_min_confidence: float = 0.8
    verdict_min_confidence: float = 0.8
    surface_tolerance_pct: float | None = None
    text_similarity: float = 0.82                # umbral de similitud para direcciones/nombres
    ocr_min_confidence: float = 65.0             # por debajo, la lectura OCR es de baja calidad (revisión visual)
    ocr_min_confidence_for_fail: float = 85.0    # un NO CUMPLE solo se sostiene con OCR de al menos esta confianza


class RuleDef(BaseModel):
    id: str
    doc_type: DocumentType
    type: str
    field: str
    provisional: bool = False
    category: str = "requisito"
    severity: str = "relevante"
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _canonical(self) -> "RuleDef":
        self.type = OPERATOR_ALIASES.get(self.type, self.type)
        if self.severity not in SEVERITIES:
            raise ValueError(f"severidad inválida '{self.severity}' en la regla {self.id}")
        return self


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
    """Acepta el YAML nativo y también el JSON del comité (`reglas_por_tipo`): este último se combina con los
    esquemas/palabras clave/cruces del conjunto por defecto."""
    try:
        data = yaml.safe_load(text)  # JSON es un subconjunto de YAML
        if isinstance(data, dict) and "reglas_por_tipo" in data:
            rs = ruleset_from_committee(data, base=RuleSet.model_validate(yaml.safe_load(DEFAULT_RULESET.read_text(encoding="utf-8"))))
        else:
            rs = RuleSet.model_validate(data)
    except (yaml.YAMLError, ValidationError, ValueError, KeyError, TypeError) as exc:
        raise RuleSetError(str(exc)) from exc
    unknown = [r.type for r in rs.rules if r.type not in STRATEGIES]
    if unknown:
        raise RuleSetError(f"Tipos de regla desconocidos: {sorted(set(unknown))}")
    return rs


def load_default_ruleset() -> RuleSet:
    return parse_ruleset(DEFAULT_RULESET.read_text(encoding="utf-8"))


def load_ruleset_file(path: str | Path) -> RuleSet:
    return parse_ruleset(Path(path).read_text(encoding="utf-8"))


# --- Adaptador del archivo del comité (reglas_comite.json) ------------------------------------
_COMMITTEE_DOC_TYPES = {"Escrituras": DocumentType.ESCRITURA, "Predial": DocumentType.PREDIAL,
                        "Alineamiento y Número Oficial": DocumentType.ALINEAMIENTO, "Uso de Suelo": DocumentType.USO_SUELO}
_COMMITTEE_FIELDS = {"superficie_terreno_m2": "superficie_terreno", "cuenta_o_clave_predial": "cuenta_predial",
                     "compatibilidad_comercial": "compatibilidad_uso_comercial", "restricciones_condicionantes": "restricciones",
                     "propietario_contribuyente": "propietario", "superficie_registrada_m2": "superficie_registrada",
                     "superficie_aplicable_m2": "superficie_aplicable", "direccion_inmueble": "direccion"}
_CATEGORY_BY_OPERATOR = {"vigente_a_fecha_actual": "vigencia", "reportar_si_existe": "restriccion"}
_PROVISIONAL_OPERATORS = {"obligatorio", "reportar_si_existe"}  # "no localizado" ≠ incumplimiento: ver principio anti falsos No cumple


def ruleset_from_committee(data: dict, base: RuleSet) -> RuleSet:
    """Convierte el formato del comité a RuleSet. Un `obligatorio`/`reportar_si_existe` es PROVISIONAL (no puede por sí solo
    producir 'No cumple', porque un campo no localizado puede ser un fallo de lectura) salvo que la regla declare "definitiva": true."""
    rules: list[RuleDef] = []
    for tipo, lista in data["reglas_por_tipo"].items():
        if tipo not in _COMMITTEE_DOC_TYPES:
            raise ValueError(f"Tipo documental desconocido en reglas_por_tipo: '{tipo}'")
        for r in lista:
            op = r["operador"]
            if op not in OPERATOR_ALIASES:
                raise ValueError(f"Operador desconocido '{op}' en la regla {r.get('id')}")
            params = {"value": r["valor"]} if "valor" in r else {}
            rules.append(RuleDef(
                id=r["id"], doc_type=_COMMITTEE_DOC_TYPES[tipo], type=op, field=_COMMITTEE_FIELDS.get(r["campo"], r["campo"]),
                provisional=op in _PROVISIONAL_OPERATORS and not r.get("definitiva", False),
                category=_CATEGORY_BY_OPERATOR.get(op, "requisito"), severity=r.get("severidad_fallo", "relevante"),
                description=r.get("descripcion", ""), params=params))
    th = base.thresholds.model_copy(update={k: v for k, v in {
        "surface_tolerance_pct": data.get("tolerancia_superficie_porcentaje"),
        "text_similarity": data.get("umbral_similitud_texto"),
        "ocr_min_confidence_for_fail": data.get("umbral_ocr_para_incumplimiento")}.items() if v is not None})
    return base.model_copy(update={"version": str(data.get("version", "comite")), "thresholds": th, "rules": rules})


# --- Strategies -------------------------------------------------------------------------

class RuleContext(BaseModel):
    reference_date: date
    fields: list[FieldValue] = Field(default_factory=list)   # para reglas que consultan campos hermanos (p. ej. fecha de emisión)
    ocr_min_confidence_for_fail: float = 85.0

    def sibling(self, rule: "RuleDef", name: str, document_id: int | None) -> FieldValue | None:
        cands = [f for f in self.fields if f.doc_type == rule.doc_type and f.name == name and f.found
                 and (document_id is None or f.evidence.document_id == document_id)]
        return next((f for f in cands if f.evidence.verification.is_trusted), cands[0] if cands else None)


class RuleStrategy(Protocol):
    def __call__(self, rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]: ...


def _required_field(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is not None and fv.found:
        return Outcome.PASS, f"Campo '{rule.field}' presente."
    return Outcome.FAIL, f"Campo '{rule.field}' no encontrado en el documento."


def _greater_than(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, f"Campo '{rule.field}' no encontrado o no verificado."
    threshold = float(rule.params.get("value", 0))
    value = parse_area_m2(fv.raw)
    if value is None:
        nums = numbers_in(fv.raw)
        value = nums[0] if nums else None
    if value is None:
        return Outcome.INDETERMINATE, f"El valor '{fv.raw}' no es numérico."
    if value > threshold:
        return Outcome.PASS, f"Valor ({value:g}) mayor a {threshold:g}."
    return Outcome.FAIL, f"Valor ({value:g}) no supera el mínimo requerido ({threshold:g})."


_OPEN_ENDED = ("indeterminad", "permanente", "indefinid", "derechos adquiridos", "sin vencimiento")
_VALIDITY_WORDS = ("vigen", "venc", "valid", "hasta", "expira", "caduc", "plazo")


def _date_not_expired(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    """Vigencia a la fecha de referencia. Soporta fecha de vencimiento, rangos ('del … al …') y plazos ('un año')
    contados desde la emisión. Ante cualquier ambigüedad devuelve INDETERMINADA."""
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, "Vigencia no encontrada."
    raw = normalize_text(fv.raw)
    if any(w in raw for w in _OPEN_ENDED):
        return Outcome.PASS, f"Vigencia permanente/indeterminada declarada ('{fv.raw}')."
    emission_fv = ctx.sibling(rule, "fecha_emision", fv.evidence.document_id)
    emission = parse_date(emission_fv.raw) if emission_fv else None
    dates, period = all_dates(fv.raw), parse_period(fv.raw)
    earliest_only = False                      # True: el vencimiento es una cota inferior (el plazo podría contar desde después)
    if period and dates:                       # 'un año a partir del 01/02/2026': inicio explícito
        expiry, origin = add_period(dates[0], *period), f"plazo de {fv.raw.strip()}"
    elif period and emission:                  # 'un año' sin inicio explícito: se asume desde la emisión (caso más temprano)
        expiry, origin = add_period(emission, *period), f"plazo '{fv.raw.strip()}' desde la emisión ({emission.isoformat()})"
        earliest_only = True
    elif period:
        return Outcome.INDETERMINATE, f"Plazo '{fv.raw}' sin fecha de emisión verificable: no se puede calcular el vencimiento."
    elif dates:
        expiry, origin = max(dates), "fecha de vencimiento declarada"   # en un rango, vale la última
        if emission and len(dates) == 1 and expiry == emission:
            return Outcome.INDETERMINATE, "La 'vigencia' coincide con la fecha de emisión: posible confusión de campos."
    else:
        return Outcome.INDETERMINATE, "La vigencia no es una fecha ni un plazo interpretable."
    if expiry >= ctx.reference_date:
        return Outcome.PASS, f"Vigente hasta {expiry.isoformat()} ({origin})."
    if earliest_only:
        return Outcome.INDETERMINATE, (f"Con el plazo contado desde la emisión el documento vencería el {expiry.isoformat()}, pero el plazo "
                                       f"podría contar desde otra fecha; verificar el original.")
    if not any(w in normalize_text(fv.evidence.quote) for w in _VALIDITY_WORDS):
        return Outcome.INDETERMINATE, f"La fecha {expiry.isoformat()} ya pasó, pero la cita no habla de vigencia; verificar que sea la fecha correcta."
    return Outcome.FAIL, f"Documento vencido el {expiry.isoformat()} ({origin})."


def _enum_match(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, f"Campo '{rule.field}' no encontrado."
    value = normalize_text(fv.raw).strip(" .")
    if value in [normalize_text(v) for v in rule.params.get("fail", [])]:
        return Outcome.FAIL, f"El documento declara: '{fv.raw}'."
    if value in [normalize_text(v) for v in rule.params.get("pass", [])]:
        return Outcome.PASS, f"El documento declara: '{fv.raw}'."
    return Outcome.INDETERMINATE, f"Valor ambiguo: '{fv.raw}'."


_TRUE_WORDS = ["si", "sí", "verdadero", "compatible", "permitido", "cumple", "true"]
_FALSE_WORDS = ["no", "falso", "incompatible", "no compatible", "prohibido", "no permitido", "false"]


def _is_true(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    """`es_verdadero`: el documento debe declarar expresamente el valor afirmativo; lo ambiguo es INDETERMINADA."""
    sub = rule.model_copy(update={"params": {"pass": rule.params.get("pass", _TRUE_WORDS), "fail": rule.params.get("fail", _FALSE_WORDS)}})
    return _enum_match(sub, fv, ctx)


def _report_if_present(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> tuple[Outcome, str]:
    if fv is None or not fv.found:
        return Outcome.INDETERMINATE, "No se pudo determinar si existen restricciones/condicionantes (campo no localizado). Verificar."
    if normalize_text(fv.raw).strip(" .") in {"ninguna", "ninguno", "no aplica", "sin restricciones", "n/a", "no hay"}:
        return Outcome.PASS, "Sin restricciones declaradas."
    return Outcome.INDETERMINATE, f"Se declaran restricciones/condicionantes: '{fv.raw}'."


STRATEGIES: dict[str, Callable[..., tuple[Outcome, str]]] = {
    "required_field": _required_field,
    "greater_than": _greater_than,
    "date_not_expired": _date_not_expired,
    "enum_match": _enum_match,
    "is_true": _is_true,
    "report_if_present": _report_if_present,
}


def evaluate_rule(rule: RuleDef, fv: FieldValue | None, ctx: RuleContext) -> RuleOutcome:
    """Evalúa una regla. Un resultado sustentado en un dato no verificado se degrada a INDETERMINADA; un NO CUMPLE
    sustentado en OCR de baja confianza o aproximado también (el dígito mal leído puede cambiar el resultado)."""
    outcome, msg = STRATEGIES[rule.type](rule, fv, ctx)
    evidence = [fv.evidence] if fv is not None and fv.found else []
    if evidence and not all(e.verification.is_trusted for e in evidence):
        outcome, msg = Outcome.INDETERMINATE, f"Evidencia no verificada. ({msg})"
    elif outcome == Outcome.FAIL and any(
            e.verification != Verification.MANUAL and e.ocr_confidence is not None
            and (e.ocr_confidence < ctx.ocr_min_confidence_for_fail or not e.exact_match) for e in evidence):
        outcome, msg = Outcome.INDETERMINATE, f"Lectura OCR no concluyente para sustentar un incumplimiento; verificar el original. ({msg})"
    return RuleOutcome(rule_id=rule.id, doc_type=rule.doc_type, outcome=outcome, provisional=rule.provisional,
                       category=rule.category, severity=rule.severity, message=msg, evidence=evidence)


def pick_field(fields: list[FieldValue], doc_type: DocumentType, name: str) -> FieldValue | None:
    """Primer valor confiable encontrado; si no, el primero encontrado; si no, cualquiera."""
    cands = [f for f in fields if f.doc_type == doc_type and f.name == name]
    for pred in (lambda f: f.found and f.evidence.verification.is_trusted, lambda f: f.found, lambda f: True):
        for f in cands:
            if pred(f):
                return f
    return None


__all__ = ["RuleSet", "RuleSetError", "parse_ruleset", "load_default_ruleset", "load_ruleset_file", "evaluate_rule",
           "pick_field", "RuleContext", "Verification", "ruleset_from_committee", "OPERATOR_ALIASES"]
