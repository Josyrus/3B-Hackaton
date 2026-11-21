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
from ..evidence import quote_coverage, verify_evidence
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


def doc_ocr_confidence(doc: DocumentInput) -> float:
    """Confianza media (0-100) de las páginas no vacías del documento; 100 si todo es texto digital; 0 si no hay texto."""
    pages = [p for p in doc.pages if not p.blank]
    return round(sum(p.ocr_confidence for p in pages) / len(pages), 2) if pages else 0.0


# ---------- 1. Ingesta -------------------------------------------------------------------
class IngestAgent(Agent):
    name, stage = "ingesta", "ingest"

    def run(self, state: DossierState) -> IngestOut:
        seen: dict[str, int] = {}
        out = IngestOut()
        min_conf = self.ruleset.thresholds.ocr_min_confidence
        for d in state.documents:
            text = nz.compact_text(_doc_text(d))   # insensible a saltos de línea/signos: detecta PDFs re-guardados
            if len(text) < 20:
                out.warnings.append(f"Documento {d.name}: sin texto legible (posible escaneo sin OCR).")
            else:
                low = [p.page for p in d.pages if not p.blank and p.method == "ocr" and p.ocr_confidence < min_conf]
                if low:
                    out.warnings.append(f"Documento {d.name}: lectura OCR de baja calidad en las páginas {low}; revisar el original.")
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
            head = doc.pages[:3]
            text = nz.normalize_text("\n".join(p.text for p in head))
            fuzzy = any(p.method == "ocr" for p in head)   # el OCR confunde letras: se tolera en palabras clave largas
            hits = {t: sum(1 for k in kws if self._keyword_hit(k, text, fuzzy))
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
            low_ocr = doc_ocr_confidence(doc) < self.ruleset.thresholds.ocr_min_confidence  # lectura dudosa: nunca se da por buena
            result.append(Classification(document_id=doc.id, doc_type=best, confidence=round(conf, 2),
                                         needs_review=conf < thr or low_ocr))
        return ClassifyOut(classifications=result)

    @staticmethod
    def _keyword_hit(keyword: str, text: str, fuzzy: bool) -> bool:
        k = nz.normalize_text(keyword)
        if k in text:
            return True
        return fuzzy and len(nz.compact_text(k)) >= 8 and quote_coverage(k, text) >= 0.88


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
                ev = verify_evidence(f.evidence, docs, f.raw, field_kind(f.name))
                if ev.verification == Verification.UNVERIFIED:
                    warnings.append(f"Cita no verificada: {f.doc_type.value}.{f.name}" + (f" ({ev.detail})" if ev.detail else ""))
                f = f.model_copy(update={"evidence": ev})
            out.append(f)
        return FieldsOut(fields=out, warnings=warnings)


# ---------- 6. Validadores por tipo documental (Strategy vía reglas YAML) ------------------------
class RuleValidatorAgent(Agent):
    name, stage = "validadores_reglas", "rules"

    def run(self, state: DossierState) -> RulesOut:
        present = {c.doc_type for c in state.classifications}
        ctx = RuleContext(reference_date=state.reference_date, fields=state.fields,
                          ocr_min_confidence_for_fail=self.ruleset.thresholds.ocr_min_confidence_for_fail)
        results = []
        for rule in self.ruleset.rules:
            if rule.doc_type not in present:
                continue
            fv = pick_field(state.fields, rule.doc_type, rule.field)
            results.append(evaluate_rule(rule, fv, ctx))
        return RulesOut(rules=results)


# ---------- 7. Validación cruzada -------------------------------------------------------------------
def _ratio(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def _token_overlap(small: list[str], big: list[str]) -> float:
    """Fracción de tokens de `small` presentes (con tolerancia a errores de OCR) en `big`."""
    return sum(1 for t in small if any(t == o or _ratio(t, o) >= 0.85 for o in big)) / len(small) if small else 0.0


def equivalent(kind: str, a: str, b: str, similarity: float) -> bool:
    """¿Dos valores normalizados designan lo mismo? Tolera datos extra (CP, alcaldía), orden de apellidos,
    coproprietarios y ruido de OCR; los números exteriores distintos SÍ son una discrepancia."""
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return False
    if kind == "address":
        da, db = {t for t in ta if t.isdigit()}, {t for t in tb if t.isdigit()}
        if da and db and da.isdisjoint(db):
            return False
        small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        return _ratio(a, b) >= similarity or _token_overlap(small, big) >= 0.7
    if kind == "name":
        small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        return (len(small) >= 2 and _token_overlap(small, big) >= 0.8) or _ratio(a, b) >= similarity
    if kind == "identifier":
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        return len(short) >= 3 and short in long_
    return False


class CrossValidationAgent(Agent):
    name, stage = "validacion_cruzada", "cross"

    def run(self, state: DossierState) -> CrossOut:
        out: list[Discrepancy] = []
        th = self.ruleset.thresholds
        for chk in self.ruleset.cross_checks:
            vals = []
            for s in chk.sources:
                fv = pick_field(state.fields, s.doc_type, s.field)
                if fv is not None and fv.found:
                    vals.append({"doc_type": s.doc_type.value, "field": s.field, "raw": fv.raw,
                                 "normalized": fv.normalized, "evidence": fv.evidence.model_dump(mode="json")})
            if len(vals) < 2:
                continue
            first = chk.sources[0]
            if chk.kind == "number_in_address" and (vals[0]["doc_type"], vals[0]["field"]) != (first.doc_type.value, first.field):
                continue  # sin el documento que fija el número oficial no hay contra qué comparar (no tomar una dirección como número)
            d = self._compare(chk.field, chk.kind, vals, th.surface_tolerance_pct, th.text_similarity)
            if d:
                out.append(d)
        # Varias discrepancias reales en dirección / titular / identificación del predio: posible mezcla de inmuebles.
        identity = [d for d in out if d.kind == "real" and d.field in ("direccion", "propietario", "identificacion_predio")]
        if len(identity) >= 2:
            for d in identity:
                d.possible_different_property = True
        return CrossOut(discrepancies=out)

    @staticmethod
    def _compare(field: str, kind: str, vals: list[dict], tol: float | None, similarity: float = 0.82) -> Discrepancy | None:
        if kind == "number_in_address":
            return CrossValidationAgent._compare_number(field, vals)
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
        conflict = any(not equivalent(kind, vals[i]["normalized"], vals[j]["normalized"], similarity)
                       for i in range(len(vals)) for j in range(i + 1, len(vals)))
        if conflict:
            return Discrepancy(field=field, kind="real", critical=True, values=vals)
        return Discrepancy(field=field, kind="formato", values=vals) if len({v["raw"] for v in vals}) > 1 else None

    @staticmethod
    def _compare_number(field: str, vals: list[dict]) -> Discrepancy | None:
        """El número oficial (primera fuente) debe aparecer en las direcciones que traigan algún número.
        No es crítica: el documento puede ratificar/actualizar un número anterior."""
        number = nz.normalize_identifier(vals[0]["raw"])
        addresses = [v for v in vals[1:] if any(t.isdigit() for t in v["normalized"].split())]
        if not number or not addresses:
            return None
        if any(number in {nz.normalize_identifier(t) for t in v["normalized"].split()} for v in addresses):
            return None
        return Discrepancy(field=field, kind="real", critical=False, values=[vals[0]] + addresses)


# ---------- 8. Dictaminador ---------------------------------------------------------------------------
NARRATIVE_SYSTEM = (
    "Eres el Agente Dictaminador del equipo legal inmobiliario. Redacta un resumen ejecutivo claro y breve (máx. 6 oraciones) "
    "sobre una recomendación YA CALCULADA por reglas deterministas. NO cambies ni cuestiones la recomendación. Cita únicamente los "
    "hallazgos proporcionados (documento y, si se da, página); no inventes datos. Responde SOLO JSON: {\"resumen\": \"...\"}.")

_LABELS = {Recommendation.PASS: "cumple", Recommendation.REVIEW: "requiere revisión", Recommendation.FAIL: "no cumple"}


class NarrativeOut(BaseModel):
    resumen: str = Field(min_length=20, max_length=2500)


def template_summary(rec: Recommendation, confidence: float, level: str, just: list[str]) -> str:
    """Resumen determinista (respaldo si no hay LLM o si el LLM falla / contradice el veredicto)."""
    head = f"Recomendación inicial: {_LABELS[rec].upper()} (confianza {level}, {confidence:.0%}). "
    body = " ".join(just[:4])
    extra = f" (+{len(just) - 4} hallazgo(s) más)" if len(just) > 4 else ""
    return head + body + extra


def summary_contradicts(summary: str, rec: Recommendation) -> bool:
    """El LLM no puede afirmar un veredicto distinto al calculado. 'No cumple' puede aparecer legítimamente al hablar de una
    regla, pero ante la duda se descarta el texto del LLM y se usa la plantilla (siempre es seguro)."""
    low = nz.normalize_text(summary)
    return any(nz.normalize_text(lbl) in low for r, lbl in _LABELS.items() if r != rec)


class VerdictAgent(Agent):
    name, stage = "dictaminador", "verdict"

    def __init__(self, ruleset: RuleSet, narrator: LLMPort | None = None) -> None:
        super().__init__(ruleset)
        self.narrator = narrator

    def run(self, state: DossierState) -> VerdictResult:
        th = self.ruleset.thresholds
        thr = th.verdict_min_confidence
        found = [f for f in state.fields if f.found]
        trusted = [f for f in found if f.evidence.verification.is_trusted]
        cls = [c for c in state.classifications if c.doc_type != DocumentType.NO_RECONOCIDO]
        determinate = [r for r in state.rules if r.outcome != Outcome.INDETERMINATE]
        used = {c.document_id for c in cls}
        ocr_docs = [doc_ocr_confidence(d) / 100.0 for d in state.documents if d.id in used]
        parts = {
            "clasificación": sum(c.confidence for c in cls) / len(cls) if cls else 0.0,
            "evidencias verificadas": len(trusted) / len(found) if found else 0.0,
            "reglas determinadas": len(determinate) / len(state.rules) if state.rules else 0.0,
            "calidad de lectura (OCR)": sum(ocr_docs) / len(ocr_docs) if ocr_docs else 0.0,
        }
        confidence = round(min(parts.values()), 2)
        level = "alta" if confidence >= 0.85 else "media" if confidence >= 0.65 else "baja"
        explanation = "Confianza = mínimo de: " + "; ".join(f"{k} {v:.0%}" for k, v in parts.items()) + "."

        review: list[str] = []
        missing = [t.value for t in state.missing]
        if missing:
            review.append(f"Documentos faltantes: {', '.join(missing)}.")
        names = {d.id: d.name for d in state.documents}
        review += [f"Clasificación de baja certeza o lectura dudosa en '{names.get(c.document_id, c.document_id)}'."
                   for c in state.classifications if c.needs_review]
        untrusted = [f for f in found if not f.evidence.verification.is_trusted]
        if untrusted:
            review.append(f"{len(untrusted)} dato(s) con evidencia no verificada.")
        real = [d for d in state.discrepancies if d.kind != "formato"]
        review += [f"Discrepancia en '{d.field}' ({d.kind})." + (" POSIBLE INMUEBLE DISTINTO." if d.possible_different_property else "") for d in real]
        indet = [r for r in state.rules if r.outcome == Outcome.INDETERMINATE]
        review += [f"Regla indeterminada: {r.rule_id} — {r.message}" for r in indet]
        prov_fail = [r for r in state.rules if r.outcome == Outcome.FAIL and r.provisional]
        review += [f"Regla provisional no satisfecha (criterio oficial pendiente): {r.rule_id}." for r in prov_fail]
        if confidence < thr:
            review.append(f"Confianza global {confidence} inferior al umbral {thr}.")

        review_docs = {c.document_id for c in state.classifications if c.needs_review}
        # "No cumple" solo con regla no provisional fallida, evidencia verificada, documento confiable y lectura sólida (no OCR dudoso/aproximado)
        solid = lambda e: (e.verification.is_trusted and e.document_id not in review_docs
                           and (e.verification == Verification.MANUAL
                                or e.ocr_confidence is None or (e.ocr_confidence >= th.ocr_min_confidence_for_fail and e.exact_match)))
        hard_fail = [r for r in state.rules if r.outcome == Outcome.FAIL and not r.provisional and r.evidence
                     and all(solid(e) for e in r.evidence)]

        satisfied = [r.rule_id for r in state.rules if r.outcome == Outcome.PASS]
        unmet = [r.rule_id for r in state.rules if r.outcome == Outcome.FAIL]
        refs = [e for r in state.rules for e in r.evidence if e.verification.is_trusted]
        incons = [f"{d.field}: " + " vs ".join(f"{v['doc_type']}='{v['raw']}'" for v in d.values)
                  + (" [POSIBLE INMUEBLE DISTINTO]" if d.possible_different_property else "") for d in real]

        if hard_fail:
            rec, just = Recommendation.FAIL, [f"Incumplimiento sustentado en evidencia verificada: {r.rule_id} — {r.message}" for r in hard_fail]
        elif review:
            rec, just = Recommendation.REVIEW, review
        else:
            rec, just = Recommendation.PASS, ["Todos los requisitos evaluados se cumplen, sin inconsistencias críticas y con confianza suficiente."]
        summary = self._narrate(rec, confidence, level, just, state, names)
        return VerdictResult(recommendation=rec, confidence=confidence, confidence_level=level, confidence_explanation=explanation,
                             executive_summary=summary, requires_human_review=rec != Recommendation.PASS, justification=just,
                             satisfied=satisfied, unmet=unmet, missing_documents=missing, inconsistencies=incons, evidence_refs=refs)

    def _narrate(self, rec: Recommendation, confidence: float, level: str, just: list[str], state: DossierState, names: dict[int, str]) -> str:
        """El LLM solo redacta; si falla, no responde JSON válido o contradice el veredicto, se usa la plantilla."""
        fallback = template_summary(rec, confidence, level, just)
        if self.narrator is None:
            return fallback
        quotes = [f"- {names.get(e.document_id, e.document_id)}, pág. {e.page}: \"{e.quote[:120]}\""
                  for r in state.rules for e in r.evidence if e.verification.is_trusted][:12]
        user = (f"Recomendación calculada: {_LABELS[rec]}\nConfianza: {level} ({confidence:.0%})\nHallazgos:\n"
                + "\n".join(f"- {j}" for j in just) + ("\nEvidencias verificadas:\n" + "\n".join(quotes) if quotes else ""))
        try:
            text = NarrativeOut.model_validate(self.narrator.complete_json(NARRATIVE_SYSTEM, user)).resumen.strip()
        except Exception:  # noqa: BLE001 - el resumen es accesorio: cualquier fallo del LLM cae a la plantilla
            return fallback
        return fallback if summary_contradicts(text, rec) else text
