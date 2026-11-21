"""Contratos estructurados (Pydantic) entre agentes. Sin dependencias de Django."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

NOT_FOUND = "no encontrado"


class DocumentType(StrEnum):
    ESCRITURA = "escritura"
    PREDIAL = "predial"
    ALINEAMIENTO = "alineamiento"
    USO_SUELO = "uso_suelo"
    NO_RECONOCIDO = "no_reconocido"


REQUIRED_TYPES = (DocumentType.ESCRITURA, DocumentType.PREDIAL,
                  DocumentType.ALINEAMIENTO, DocumentType.USO_SUELO)


class Outcome(StrEnum):
    PASS = "cumple"
    FAIL = "no_cumple"
    INDETERMINATE = "indeterminada"


class Recommendation(StrEnum):
    PASS = "cumple"
    REVIEW = "requiere_revision"
    FAIL = "no_cumple"


class Verification(StrEnum):
    PENDING = "pendiente"
    VERIFIED = "verificada"
    UNVERIFIED = "no_verificada"
    MANUAL = "corregida_manualmente"

    @property
    def is_trusted(self) -> bool:
        return self in (Verification.VERIFIED, Verification.MANUAL)


class PageText(BaseModel):
    page: int = Field(ge=1)
    text: str = ""


class DocumentInput(BaseModel):
    id: int
    name: str
    pages: list[PageText]


class Evidence(BaseModel):
    document_id: int | None = None
    page: int | None = None
    quote: str = ""
    verification: Verification = Verification.PENDING


class FieldValue(BaseModel):
    doc_type: DocumentType
    name: str
    raw: str = NOT_FOUND
    normalized: str = NOT_FOUND
    evidence: Evidence = Field(default_factory=Evidence)
    origin: str = "agent"

    @property
    def found(self) -> bool:
        return self.raw != NOT_FOUND


class Classification(BaseModel):
    document_id: int
    doc_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    manual: bool = False


class RuleOutcome(BaseModel):
    rule_id: str
    doc_type: DocumentType | None = None
    outcome: Outcome
    provisional: bool = False
    category: str = "requisito"  # requisito | vigencia | restriccion | completitud
    message: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class Discrepancy(BaseModel):
    field: str
    kind: str  # formato | real | tolerancia_pendiente
    critical: bool = False
    values: list[dict] = Field(default_factory=list)  # {doc_type, raw, normalized, evidence}


class VerdictResult(BaseModel):
    recommendation: Recommendation
    confidence: float
    justification: list[str]
    satisfied: list[str] = Field(default_factory=list)
    unmet: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    inconsistencies: list[str] = Field(default_factory=list)
    evidence_refs: list[Evidence] = Field(default_factory=list)
    disclaimer: str = ("Recomendación inicial automatizada; no constituye una decisión legal definitiva.")


class DossierState(BaseModel):
    """Estado compartido del expediente. Solo el supervisor lo modifica."""
    dossier_id: int
    required_use: str = ""
    reference_date: date = Field(default_factory=date.today)
    documents: list[DocumentInput] = Field(default_factory=list)
    duplicates: list[int] = Field(default_factory=list)
    classifications: list[Classification] = Field(default_factory=list)
    missing: list[DocumentType] = Field(default_factory=list)
    fields: list[FieldValue] = Field(default_factory=list)
    rules: list[RuleOutcome] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    verdict: VerdictResult | None = None
    warnings: list[str] = Field(default_factory=list)
