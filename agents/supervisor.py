from __future__ import annotations

import logging
from typing import Optional

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.analyst import AnalystAgent
from agents.enforcement import EnforcementAgent
from core.models import ChallanDraft, RootCauseVerdict, ViolationEvent

log = logging.getLogger(__name__)


class SaarthiState(TypedDict, total=False):
    """Shared state passed between agents in the supervisor graph."""

    features: dict
    benchmark: Optional[dict]
    parking_report: Optional[dict]
    verdict: Optional[RootCauseVerdict]
    violation_event: Optional[ViolationEvent]
    challan_id: Optional[int]
    challan: Optional[ChallanDraft]


def _analyst_node(state: SaarthiState) -> dict:
    verdict = AnalystAgent().analyze(state["features"], state.get("benchmark"),
                                     state.get("parking_report"))
    return {"verdict": verdict}


def _enforcement_node(state: SaarthiState) -> dict:
    challan_id, draft = EnforcementAgent().process(state["violation_event"])
    return {"challan_id": challan_id, "challan": draft}


def _route_start(state: SaarthiState) -> str:
    if state.get("features"):
        return "analyst"
    if state.get("violation_event"):
        return "enforcement"
    return END


def _route_after_analyst(state: SaarthiState) -> str:
    return "enforcement" if state.get("violation_event") else END


def build_supervisor():
    """Compile and return the supervisor graph."""
    graph = StateGraph(SaarthiState)
    graph.add_node("analyst", _analyst_node)
    graph.add_node("enforcement", _enforcement_node)
    graph.add_conditional_edges(START, _route_start,
                                {"analyst": "analyst", "enforcement": "enforcement", END: END})
    graph.add_conditional_edges("analyst", _route_after_analyst,
                                {"enforcement": "enforcement", END: END})
    graph.add_edge("enforcement", END)
    return graph.compile()
