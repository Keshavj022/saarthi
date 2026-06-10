"""LangGraph supervisor — the slow reasoning layer's coordinator.

Holds the shared analysis state and routes it to the Analyst. The graph is the
extension point: the Enforcement agent (Phase 4) is added as another node, and
conditional edges can route between them. For Phase 2 the flow is simply
START → analyst → END.
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.analyst import AnalystAgent
from core.models import RootCauseVerdict

log = logging.getLogger(__name__)


class SaarthiState(TypedDict, total=False):
    """Shared state passed between agents in the supervisor graph."""

    features: dict
    benchmark: Optional[dict]
    verdict: Optional[RootCauseVerdict]


def _analyst_node(state: SaarthiState) -> dict:
    verdict = AnalystAgent().analyze(state["features"], state.get("benchmark"))
    return {"verdict": verdict}


def build_supervisor():
    """Compile and return the supervisor graph."""
    graph = StateGraph(SaarthiState)
    graph.add_node("analyst", _analyst_node)
    graph.add_edge(START, "analyst")
    graph.add_edge("analyst", END)
    return graph.compile()
