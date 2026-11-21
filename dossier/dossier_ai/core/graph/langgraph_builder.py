"""Construcción del flujo como grafo LangGraph (misma lógica de agentes y de enrutamiento que el Supervisor).

El estado del grafo es `DossierState` (el "ExpedienteState" del diseño): cada nodo ejecuta un agente, aplica su salida con
`_apply` (único punto de escritura) y devuelve el estado completo, por lo que la información previa se conserva sin
necesidad de reducers; la bitácora (`log`) y las alertas (`warnings`) se acumulan dentro del propio estado.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..contracts import DossierState, LogEntry
from .supervisor import SKIPPABLE, STAGES, Supervisor, _apply, route_after_missing, summarize


def build_langgraph(supervisor: Supervisor):
    def make_node(stage: str):
        def node(state: DossierState) -> dict:
            agent = supervisor.agents[stage]
            new = state.model_copy(deep=True)
            if stage == "verdict" and route_after_missing(new) == "verdict":  # etapas omitidas por la arista condicional: se registran igual que en el Supervisor
                for skipped in SKIPPABLE:
                    new.log.append(LogEntry(agent=supervisor.agents[skipped].name, stage=skipped, status="skipped",
                                            summary="sin documentos extraíbles"))
            warn0 = len(new.warnings)
            out = agent.run(state)
            _apply(stage, new, out)
            new.log.append(LogEntry(agent=agent.name, stage=stage, status="warning" if len(new.warnings) > warn0 else "ok",
                                    summary=summarize(stage, out)))
            return new.model_dump()
        return node

    g = StateGraph(DossierState)
    for s in STAGES:
        g.add_node(s, make_node(s))
    g.add_edge(START, STAGES[0])
    for a, b in zip(STAGES, STAGES[1:]):
        if a != "missing":       # "missing" tiene salida condicional
            g.add_edge(a, b)
    # Transición condicional: sin documentos extraíbles se salta directamente al dictamen (nunca se detiene).
    g.add_conditional_edges("missing", route_after_missing, {"extract": "extract", "verdict": "verdict"})
    g.add_edge(STAGES[-1], END)
    return g.compile()
