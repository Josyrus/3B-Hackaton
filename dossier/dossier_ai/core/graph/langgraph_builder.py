"""Construcción opcional del mismo flujo como grafo LangGraph (misma lógica de agentes)."""
from __future__ import annotations

from ..contracts import DossierState
from .supervisor import STAGES, Supervisor, _apply


def build_langgraph(supervisor: Supervisor):
    from langgraph.graph import END, START, StateGraph

    def make_node(stage: str):
        def node(state: DossierState) -> dict:
            out = supervisor.agents[stage].run(state)
            new = state.model_copy(deep=True)
            _apply(stage, new, out)
            return new.model_dump()
        return node

    g = StateGraph(DossierState)
    for s in STAGES:
        g.add_node(s, make_node(s))
    g.add_edge(START, STAGES[0])
    for a, b in zip(STAGES, STAGES[1:]):
        g.add_edge(a, b)
    g.add_edge(STAGES[-1], END)
    return g.compile()
