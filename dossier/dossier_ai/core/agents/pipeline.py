"""Agentes: ingesta, clasificador, faltantes, extractores, verificador, validadores, cruzada, dictamen."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from pydantic import BaseModel, Field, ValidationError

from .. import normalization as nz
from ..contracts import (NOT_FOUND, REQUIRED_TYPES, Classification, Discrepancy, DocumentInput, DocumentType,
                         DossierState, Evidence, FieldValue, Outcome, Recommendation, RuleOutcome,
                         VerdictResult, Verification)
from ..evidence import verify_evidence
from ..ports import LLMPort
from ..rules import RuleContext, RuleSet, evaluate_rule, pick_field
from .base import Agent


# ---------- Salidas estructuradas ------------------------------------------------------
class IngestOut(BaseModel):
    duplicates: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClassifyOut(BaseModel):
    classifications: list[Classification]


class MissingOut(BaseModel):
    missing: list[DocumentType]


class FieldsOut(BaseModel):
    fields: list[FieldValue]
    warnings: list[str] = Field(default_factory=list)


class RulesOut(BaseModel):
    rules: list[RuleOutcome]


class CrossOut(BaseModel):
    discrepancies: list[Discrepancy]


def field_kind(name: str) -> str:
    if name.startswith("direccion"):
        return "address"
    if name in ("titular", "propietario"):
        return "name"
    if name.startswith("superficie"):
        return "area"
    if name in ("fecha_emision", "vigencia"):
        return "date"
    if name in ("cuenta_predial", "numero_oficial") or name.startswith("identificacion"):
        return "identifier"
    return "text"


def normalize_value(kind: str, raw: str) -> str:
    return {"address": nz.normalize_address, "name": nz.normalize_name, "area": nz.normalize_area,
            "date": nz.normalize_date, "identifier": nz.normalize_identifier}.get(kind, nz.normalize_text)(raw)


def _doc_text(doc: DocumentInput) -> str:
    return "\n".join(p.text for p in doc.pages)


# ---------- 1. Ingesta -------------------------------------------------------------------
class IngestAgent(Agent):
    name, stage = "ingesta", "ingest"

    def run(self, state: DossierState) -> IngestOut:
        seen: dict[str, int] = {}
        out = IngestOut()
        for d in state.documents:
            text = nz.normalize_text(_doc_text(d))
            if len(text) < 20:
                out.warnings.append(f"Documento {d.name}: sin texto legible (posible escaneo sin OCR).")
            digest = hashlib.sha256(text.encode()).hexdigest()
            if len(text) >= 20 and digest in seen:
                out.duplicates.append(d.id)
            else:
                seen.setdefault(digest, d.id)
        if not state.documents:
            out.warnings.append("El expediente no contiene documentos procesables.")
        return out


# ---------- 2. Clasificador ----------------------------------------------------------------
class ClassifierAgent(Agent):
    name, stage = "clasificador", "classify"

    def run(self, state: DossierState) -> ClassifyOut:
        manual = {c.document_id: c for c in state.classifications if c.manual}
        thr = self.ruleset.thresholds.classification_min_confidence
        result: list[Classification] = list(manual.values())
        for doc in state.documents:
            if doc.id in manual:
                continue
            text = nz.normalize_text("\n".join(p.text for p in doc.pages[:3]))
            hits = {t: sum(1 for k in kws if nz.normalize_text(k) in text)
                    for t, kws in self.ruleset.classification_keywords.items()}
            ranked = sorted(hits.items(), key=lambda kv: kv[1], reverse=True)
            best, n = ranked[0]
            if n == 0:
                result.append(Classification(document_id=doc.id, doc_type=DocumentType.NO_RECONOCIDO,
                                             confidence=0.0, needs_review=True))
                continue
            conf = min(1.0, 0.4 + 0.2 * n)
            if len(ranked) > 1 and ranked[1][1] >= n:
                conf *= 0.6  # ambigüedad entre tipos
            result.append(Classification(document_id=doc.id, doc_type=best, confidence=round(conf, 2),
                                         needs_review=conf < thr))
        return ClassifyOut(classifications=result)


# ---------- 3. Faltantes -------------------------------------------------------------------
class MissingAgent(Agent):
    name, stage = "detector_faltantes", "missing"

    def run(self, state: DossierState) -> MissingOut:
        present = {c.doc_type for c in state.classifications}
        return MissingOut(missing=[t for t in REQUIRED_TYPES if t not in present])


# ---------- 4. Extractores (Template Method + Factory) ---------------------------------------
class BaseExtractor:
    """Flujo común: segmentar → obtener candidatos → normalizar → anclar evidencia."""
    doc_type: DocumentType

    def __init__(self, ruleset: RuleSet) -> None:
        self.schema = ruleset.schemas[self.doc_type]

    def extract(self, doc: DocumentInput) -> tuple[list[FieldValue], list[str]]:
        candidates, warnings = self.candidates(doc)
        out = []
        for name in self.schema:
            c = candidates.get(name)
            if c is None:
                out.append(FieldValue(doc_type=self.doc_type, name=name, evidence=Evidence(document_id=doc.id)))
                continue
            raw, page, quote = c
            out.append(FieldValue(
                doc_type=self.doc_type, name=name, raw=raw.strip(),
                normalized=normalize_value(field_kind(name), raw),
                evidence=Evidence(document_id=doc.id, page=page, quote=quote)))
        return out, warnings

    def candidates(self, doc: DocumentInput) -> tuple[dict[str, tuple[str, int, str]], list[str]]:
        raise NotImplementedError


class LabelExtractor(BaseExtractor):
    """Extractor determinista local basado en las etiquetas del esquema. Reconoce tres formas:
    'Campo: valor', 'Campo' + valor en la línea siguiente, y 'Campo valor' (etiquetas de 2+ palabras)."""
    _LINE = re.compile(r"^\s*(.+?)\s*[:：]\s*(\S.*)$")

    def candidates(self, doc):
        labels = {n: {nz.normalize_text(label) for label in ls} for n, ls in self.schema.items()}
        found: dict[str, tuple[str, int, str]] = {}
        for page in doc.pages:
            lines = [ln for ln in page.text.splitlines() if ln.strip()]
            for i, line in enumerate(lines):
                hit = self._match(line, lines[i + 1] if i + 1 < len(lines) else "", labels)
                for name, raw, quote in hit:
                    found.setdefault(name, (raw, page.page, quote))
        return found, []

    def _match(self, line: str, nxt: str, labels: dict[str, set[str]]) -> list[tuple[str, str, str]]:
        m = self._LINE.match(line)
        if m:  # 'Campo: valor'
            label = nz.normalize_text(m[1])
            return [(n, m[2], line.strip()) for n, acc in labels.items() if label in acc]
        norm = nz.normalize_text(line).rstrip(" :")
        out = []
        for name, acc in labels.items():
            if norm in acc and nxt.strip() and not self._LINE.match(nxt):  # etiqueta sola + valor debajo
                out.append((name, nxt.strip(), f"{line.strip()} {nxt.strip()}"))
                continue
            for label in sorted(acc, key=len, reverse=True):  # 'Campo valor' (solo etiquetas de 2+ palabras)
                if " " in label and norm.startswith(label + " "):
                    start = len(line) - len(line.lstrip())
                    words = len(label.split())
                    raw = " ".join(line.split()[words:])
                    if raw:
                        out.append((name, raw, line.strip()))
                    break
        return out


class LLMExtractionItem(BaseModel):
    name: str
    value: str
    page: int
    quote: str


class LLMExtraction(BaseModel):
    fields: list[LLMExtractionItem]


class LLMExtractor(BaseExtractor):
    """Extractor con LLM local vía LLMPort. La salida se valida con Pydantic y las citas se
    verifican después de forma independiente; el LLM nunca decide el estado de verificación."""

    def __init__(self, ruleset: RuleSet, llm: LLMPort, system_prompt: str) -> None:
        super().__init__(ruleset)
        self.llm, self.system_prompt = llm, system_prompt

    def candidates(self, doc):
        body = "\n".join(f"[PÁGINA {p.page}]\n{p.text}" for p in doc.pages)
        user = f"Campos válidos: {list(self.schema)}\n\n{body}"
        try:
            parsed = LLMExtraction.model_validate(self.llm.complete_json(self.system_prompt, user))
        except (ValidationError, ValueError, KeyError) as exc:
            return {}, [f"Salida inválida del LLM para {doc.name}: {type(exc).__name__}"]
        found = {i.name: (i.value, i.page, i.quote) for i in parsed.fields
                 if i.name in self.schema and i.value.strip() and i.name not in {}}
        return found, []


EXTRACTOR_CLASSES = {t: type(f"{t.name.title()}Extractor", (LabelExtractor,), {"doc_type": t}) for t in REQUIRED_TYPES}


class ExtractorFactory:
    """Factory Method: crea el extractor adecuado por tipo documental."""

    def __init__(self, ruleset: RuleSet, llm: LLMPort | None = None, system_prompt: str = "") -> None:
        self.ruleset, self.llm, self.prompt = ruleset, llm, system_prompt

    def create(self, doc_type: DocumentType) -> BaseExtractor:
        if doc_type not in EXTRACTOR_CLASSES:
            raise KeyError(f"Sin extractor para {doc_type}")
        if self.llm is not None:
            cls = type(f"{doc_type.name.title()}LLMExtractor", (LLMExtractor,), {"doc_type": doc_type})
            return cls(self.ruleset, self.llm, self.prompt)
        return EXTRACTOR_CLASSES[doc_type](self.ruleset)


class ExtractionAgent(Agent):
    name, stage = "extractores", "extract"

    def __init__(self, ruleset: RuleSet, factory: ExtractorFactory | None = None) -> None:
        super().__init__(ruleset)
        self.factory = factory or ExtractorFactory(ruleset)

    def run(self, state: DossierState) -> FieldsOut:
        docs = {d.id: d for d in state.documents}
        manual = [f for f in state.fields if f.origin == "manual"]
        out, warnings = list(manual), []
        manual_keys = {(f.doc_type, f.name, f.evidence.document_id) for f in manual}
        for c in state.classifications:
            if c.doc_type == DocumentType.NO_RECONOCIDO or c.document_id in state.duplicates:
                continue
            fields, w = self.factory.create(c.doc_type).extract(docs[c.document_id])
            out.extend(f for f in fields if (f.doc_type, f.name, c.document_id) not in manual_keys)
            warnings += w
        return FieldsOut(fields=out, warnings=warnings)


# ---------- 5. Verificador independiente -------------------------------------------------------
class EvidenceVerifierAgent(Agent):
    name, stage = "verificador_evidencia", "verify"

    def run(self, state: DossierState) -> FieldsOut:
        docs = {d.id: d for d in state.documents}
        out, warnings = [], []
        for f in state.fields:
            if f.found:
                ev = verify_evidence(f.evidence, docs)
                if ev.verification == Verification.UNVERIFIED:
                    warnings.append(f"Cita no verificada: {f.doc_type.value}.{f.name}")
                f = f.model_copy(update={"evidence": ev})
            out.append(f)
        return FieldsOut(fields=out, warnings=warnings)


# ---------- 6. Validadores por tipo documental (Strategy vía reglas YAML) ------------------------
class RuleValidatorAgent(Agent):
    name, stage = "validadores_reglas", "rules"

    def run(self, state: DossierState) -> RulesOut:
        present = {c.doc_type for c in state.classifications}
        ctx = RuleContext(reference_date=state.reference_date)
        results = []
        for rule in self.ruleset.rules:
            if rule.doc_type not in present:
                continue
            fv = pick_field(state.fields, rule.doc_type, rule.field)
            results.append(evaluate_rule(rule, fv, ctx))
        return RulesOut(rules=results)


# ---------- 7. Validación cruzada -------------------------------------------------------------------
class CrossValidationAgent(Agent):
    name, stage = "validacion_cruzada", "cross"

    def run(self, state: DossierState) -> CrossOut:
        out: list[Discrepancy] = []
        tol = self.ruleset.thresholds.surface_tolerance_pct
        for chk in self.ruleset.cross_checks:
            vals = []
            for s in chk.sources:
                fv = pick_field(state.fields, s.doc_type, s.field)
                if fv is not None and fv.found:
                    vals.append({"doc_type": s.doc_type.value, "field": s.field, "raw": fv.raw,
                                 "normalized": fv.normalized, "evidence": fv.evidence.model_dump(mode="json")})
            if len(vals) < 2:
                continue
            d = self._compare(chk.field, chk.kind, vals, tol)
            if d:
                out.append(d)
        return CrossOut(discrepancies=out)

    @staticmethod
    def _compare(field: str, kind: str, vals: list[dict], tol: float | None) -> Discrepancy | None:
        if kind == "area":
            areas = [nz.parse_area_m2(v["raw"]) for v in vals]
            if any(a is None for a in areas):
                return Discrepancy(field=field, kind="tolerancia_pendiente", values=vals)
            lo, hi = min(areas), max(areas)  # type: ignore[type-var]
            if lo == hi:
                return Discrepancy(field=field, kind="formato", values=vals) if len({v["raw"] for v in vals}) > 1 else None
            if tol is None:
                return Discrepancy(field=field, kind="tolerancia_pendiente", values=vals)
            if hi and (hi - lo) / hi * 100 <= tol:
                return Discrepancy(field=field, kind="formato", values=vals)
            return Discrepancy(field=field, kind="real", critical=True, values=vals)
        if len({v["normalized"] for v in vals}) == 1:
            return Discrepancy(field=field, kind="formato", values=vals) if len({v["raw"] for v in vals}) > 1 else None
        return Discrepancy(field=field, kind="real", critical=True, values=vals)


# ---------- 8. Dictaminador ---------------------------------------------------------------------------
class VerdictAgent(Agent):
    name, stage = "dictaminador", "verdict"

    def run(self, state: DossierState) -> VerdictResult:
        thr = self.ruleset.thresholds.verdict_min_confidence
        found = [f for f in state.fields if f.found]
        trusted = [f for f in found if f.evidence.verification.is_trusted]
        cls = [c for c in state.classifications if c.doc_type != DocumentType.NO_RECONOCIDO]
        determinate = [r for r in state.rules if r.outcome != Outcome.INDETERMINATE]
        confidence = round(min(
            sum(c.confidence for c in cls) / len(cls) if cls else 0.0,
            len(trusted) / len(found) if found else 0.0,
            len(determinate) / len(state.rules) if state.rules else 0.0), 2)

        review: list[str] = []
        missing = [t.value for t in state.missing]
        if missing:
            review.append(f"Documentos faltantes: {', '.join(missing)}.")
        review += [f"Clasificación de baja certeza en documento {c.document_id}." for c in state.classifications if c.needs_review]
        untrusted = [f for f in found if not f.evidence.verification.is_trusted]
        if untrusted:
            review.append(f"{len(untrusted)} dato(s) con evidencia no verificada.")
        real = [d for d in state.discrepancies if d.kind != "formato"]
        review += [f"Discrepancia en '{d.field}' ({d.kind})." for d in real]
        indet = [r for r in state.rules if r.outcome == Outcome.INDETERMINATE]
        review += [f"Regla indeterminada: {r.rule_id} — {r.message}" for r in indet]
        prov_fail = [r for r in state.rules if r.outcome == Outcome.FAIL and r.provisional]
        review += [f"Regla provisional no satisfecha (criterio oficial pendiente): {r.rule_id}." for r in prov_fail]
        if confidence < thr:
            review.append(f"Confianza global {confidence} inferior al umbral {thr}.")

        review_docs = {c.document_id for c in state.classifications if c.needs_review}
        hard_fail = [r for r in state.rules if r.outcome == Outcome.FAIL and not r.provisional and r.evidence
                     and all(e.verification.is_trusted and e.document_id not in review_docs for e in r.evidence)]

        satisfied = [r.rule_id for r in state.rules if r.outcome == Outcome.PASS]
        unmet = [r.rule_id for r in state.rules if r.outcome == Outcome.FAIL]
        refs = [e for r in state.rules for e in r.evidence if e.verification.is_trusted]
        incons = [f"{d.field}: " + " vs ".join(f"{v['doc_type']}='{v['raw']}'" for v in d.values) for d in real]

        if hard_fail:
            rec, just = Recommendation.FAIL, [f"Incumplimiento sustentado en evidencia verificada: {r.rule_id} — {r.message}" for r in hard_fail]
        elif review:
            rec, just = Recommendation.REVIEW, review
        else:
            rec, just = Recommendation.PASS, ["Todos los requisitos evaluados se cumplen, sin inconsistencias críticas y con confianza suficiente."]
        return VerdictResult(recommendation=rec, confidence=confidence, justification=just, satisfied=satisfied,
                             unmet=unmet, missing_documents=missing, inconsistencies=incons, evidence_refs=refs)
