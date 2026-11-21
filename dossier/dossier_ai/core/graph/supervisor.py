"""Orquestador/Supervisor con Observer. Aplica la salida de cada agente al estado compartido."""
from __future__ import annotations

import time
from typing import Callable, Protocol

from pydantic import BaseModel

from ..agents.base import Agent
from ..agents.pipeline import (ClassifierAgent, CrossValidationAgent, EvidenceVerifierAgent, ExtractionAgent,
                               IngestAgent, MissingAgent, RuleValidatorAgent, VerdictAgent, ExtractorFactory)
from ..contracts import DocumentType, DossierState, LogEntry
from ..ports import LLMPort
from ..rules import RuleSet

STAGES = ["ingest", "classify", "missing", "extract", "verify", "rules", "cross", "verdict"]
# Etapas que carecen de sentido si no hay ningún documento extraíble: el flujo salta directo al dictamen.
SKIPPABLE = ("extract", "verify", "rules", "cross")


class Observer(Protocol):
    def on_event(self, event: str, agent: str, stage: str, payload: dict) -> None: ...


class NullObserver:
    def on_event(self, event: str, agent: str, stage: str, payload: dict) -> None:
        return None


def has_extractable_documents(state: DossierState) -> bool:
    """¿Queda algún documento clasificado (no 'no reconocido') y no duplicado del que extraer datos?"""
    return any(c.doc_type != DocumentType.NO_RECONOCIDO and c.document_id not in state.duplicates for c in state.classifications)


def route_after_missing(state: DossierState) -> str:
    """Transición condicional compartida por el Supervisor y el grafo LangGraph."""
    return "extract" if has_extractable_documents(state) else "verdict"


def _apply(stage: str, state: DossierState, out: BaseModel) -> None:
    """Único punto donde el estado compartido se modifica."""
    if stage == "ingest":
        state.duplicates, state.warnings = out.duplicates, state.warnings + out.warnings  # type: ignore[attr-defined]
    elif stage == "classify":
        state.classifications = out.classifications  # type: ignore[attr-defined]
    elif stage == "missing":
        state.missing = out.missing  # type: ignore[attr-defined]
    elif stage in ("extract", "verify"):
        state.fields = out.fields  # type: ignore[attr-defined]
        state.warnings += out.warnings  # type: ignore[attr-defined]
    elif stage == "rules":
        state.rules = out.rules  # type: ignore[attr-defined]
    elif stage == "cross":
        state.discrepancies = out.discrepancies  # type: ignore[attr-defined]
    elif stage == "verdict":
        state.verdict = out  # type: ignore[assignment]


def summarize(stage: str, out: BaseModel) -> str:
    """Resumen corto y sin contenido documental de la salida de un agente (para la bitácora)."""
    n = lambda attr: len(getattr(out, attr, []) or [])  # noqa: E731
    return {
        "ingest": f"{n('duplicates')} duplicado(s), {n('warnings')} aviso(s)",
        "classify": f"{n('classifications')} documento(s) clasificado(s)",
        "missing": f"faltantes: {n('missing')}",
        "extract": f"{n('fields')} campo(s), {n('warnings')} aviso(s)",
        "verify": f"{n('fields')} campo(s) auditado(s), {n('warnings')} cita(s) no verificada(s)",
        "rules": f"{n('rules')} regla(s) evaluada(s)",
        "cross": f"{n('discrepancies')} discrepancia(s)",
        "verdict": f"recomendación: {getattr(getattr(out, 'recommendation', None), 'value', '?')}",
    }.get(stage, "")


class Supervisor:
    def __init__(self, ruleset: RuleSet, observer: Observer | None = None, factory: ExtractorFactory | None = None,
                 max_retries: int = 2, sleep: Callable[[float], None] = time.sleep, narrator: LLMPort | None = None) -> None:
        self.observer = observer or NullObserver()
        self.max_retries, self.sleep = max_retries, sleep
        self.agents: dict[str, Agent] = {a.stage: a for a in [
            IngestAgent(ruleset), ClassifierAgent(ruleset), MissingAgent(ruleset),
            ExtractionAgent(ruleset, factory), EvidenceVerifierAgent(ruleset), RuleValidatorAgent(ruleset),
            CrossValidationAgent(ruleset), VerdictAgent(ruleset, narrator)]}

    def run(self, state: DossierState, from_stage: str = "ingest") -> DossierState:
        for stage in STAGES[STAGES.index(from_stage):]:
            agent = self.agents[stage]
            if stage in SKIPPABLE and route_after_missing(state) == "verdict":
                state.log.append(LogEntry(agent=agent.name, stage=stage, status="skipped", summary="sin documentos extraíbles"))
                self.observer.on_event("skip", agent.name, stage, {"progress": round(100 * STAGES.index(stage) / len(STAGES))})
                continue
            self.observer.on_event("start", agent.name, stage, {"progress": round(100 * (STAGES.index(stage)) / len(STAGES))})
            t0, attempt, warn0 = time.perf_counter(), 0, len(state.warnings)
            while True:
                try:
                    out = agent.run(state)
                    break
                except Exception as exc:  # noqa: BLE001 - reintento acotado y registro; se relanza al agotar
                    attempt += 1
                    self.observer.on_event("retry", agent.name, stage, {"error": type(exc).__name__, "attempt": attempt})
                    if attempt > self.max_retries:
                        state.log.append(LogEntry(agent=agent.name, stage=stage, status="error", retries=attempt - 1,
                                                  duration_ms=int((time.perf_counter() - t0) * 1000), summary=type(exc).__name__))
                        self.observer.on_event("error", agent.name, stage, {"error": type(exc).__name__, "retries": attempt - 1})
                        raise
                    self.sleep(0.5 * attempt)
            _apply(stage, state, out)
            duration = int((time.perf_counter() - t0) * 1000)
            state.log.append(LogEntry(agent=agent.name, stage=stage, status="warning" if len(state.warnings) > warn0 else "ok",
                                      duration_ms=duration, retries=attempt, summary=summarize(stage, out)))
            self.observer.on_event("finish", agent.name, stage, {
                "output": out.model_dump(mode="json"), "duration_ms": duration,
                "retries": attempt, "progress": round(100 * (STAGES.index(stage) + 1) / len(STAGES))})
        return state
