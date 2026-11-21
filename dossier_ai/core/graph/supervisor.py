"""Orquestador/Supervisor con Observer. Aplica la salida de cada agente al estado compartido."""
from __future__ import annotations

import time
from typing import Callable, Protocol

from pydantic import BaseModel

from ..agents.base import Agent
from ..agents.pipeline import (ClassifierAgent, CrossValidationAgent, EvidenceVerifierAgent, ExtractionAgent,
                               IngestAgent, MissingAgent, RuleValidatorAgent, VerdictAgent, ExtractorFactory)
from ..contracts import DossierState
from ..rules import RuleSet

STAGES = ["ingest", "classify", "missing", "extract", "verify", "rules", "cross", "verdict"]


class Observer(Protocol):
    def on_event(self, event: str, agent: str, stage: str, payload: dict) -> None: ...


class NullObserver:
    def on_event(self, event: str, agent: str, stage: str, payload: dict) -> None:
        return None


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


class Supervisor:
    def __init__(self, ruleset: RuleSet, observer: Observer | None = None, factory: ExtractorFactory | None = None,
                 max_retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> None:
        self.observer = observer or NullObserver()
        self.max_retries, self.sleep = max_retries, sleep
        self.agents: dict[str, Agent] = {a.stage: a for a in [
            IngestAgent(ruleset), ClassifierAgent(ruleset), MissingAgent(ruleset),
            ExtractionAgent(ruleset, factory), EvidenceVerifierAgent(ruleset), RuleValidatorAgent(ruleset),
            CrossValidationAgent(ruleset), VerdictAgent(ruleset)]}

    def run(self, state: DossierState, from_stage: str = "ingest") -> DossierState:
        for i, stage in enumerate(STAGES[STAGES.index(from_stage):]):
            agent = self.agents[stage]
            self.observer.on_event("start", agent.name, stage, {"progress": round(100 * (STAGES.index(stage)) / len(STAGES))})
            t0, attempt = time.perf_counter(), 0
            while True:
                try:
                    out = agent.run(state)
                    break
                except Exception as exc:  # noqa: BLE001 - reintento acotado y registro; se relanza al agotar
                    attempt += 1
                    self.observer.on_event("retry", agent.name, stage, {"error": type(exc).__name__, "attempt": attempt})
                    if attempt > self.max_retries:
                        self.observer.on_event("error", agent.name, stage, {"error": type(exc).__name__, "retries": attempt - 1})
                        raise
                    self.sleep(0.5 * attempt)
            _apply(stage, state, out)
            self.observer.on_event("finish", agent.name, stage, {
                "output": out.model_dump(mode="json"), "duration_ms": int((time.perf_counter() - t0) * 1000),
                "retries": attempt, "progress": round(100 * (STAGES.index(stage) + 1) / len(STAGES))})
        return state
