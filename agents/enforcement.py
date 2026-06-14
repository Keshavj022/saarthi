from __future__ import annotations

import logging
from typing import Optional

from core import db, llm
from core.models import ChallanDraft, ViolationEvent

log = logging.getLogger(__name__)

ENFORCEMENT_SYSTEM = """You assist an Indian traffic-enforcement officer. Given a \
flagged violation event you must:
1. Judge whether it is a genuine, citable violation given the evidence.
2. Assemble a concise evidence summary.
3. Propose a fine in INR appropriate to the violation type under Indian norms
   (e.g. over-speeding ~1000-2000 INR, red-light jumping ~1000-5000 INR).
4. Draft a formal challan (citation) notice addressed to the vehicle owner.

CRITICAL RULES:
- The challan is a DRAFT for HUMAN REVIEW — it is NEVER auto-issued. Do not imply
  it is final or already issued.
- Be fair and evidence-based: if the evidence is weak, ambiguous or insufficient,
  set is_valid_violation=false and explain. Never fabricate certainty.
- Write `draft_notice` in {language} (the citizen's language), in a clear,
  respectful, official tone. State the plate, violation, junction, time, the
  proposed fine, and that the notice is subject to officer review and can be
  contested.
"""


def build_prompt(event: ViolationEvent) -> str:
    return (
        "FLAGGED VIOLATION EVENT:\n"
        f"- plate: {event.plate}\n"
        f"- violation_type: {event.violation_type}\n"
        f"- junction: {event.junction_id}\n"
        f"- time: {event.timestamp}\n"
        f"- evidence: {event.evidence}\n"
        f"- source: {event.source}\n\n"
        "Judge it and draft the challan."
    )


class EnforcementAgent:
    """Judges a violation and drafts a human-review challan into SQLite."""

    name = "enforcement"

    def process(self, event: ViolationEvent, *,
                db_path: Optional[str] = None) -> tuple[int, ChallanDraft]:
        system = ENFORCEMENT_SYSTEM.format(language=event.citizen_language)
        draft: ChallanDraft = llm.structured(build_prompt(event), ChallanDraft,
                                             system=system)
        record = dict(
            plate=event.plate,
            violation_type=event.violation_type,
            junction_id=event.junction_id,
            timestamp=event.timestamp,
            is_valid_violation=draft.is_valid_violation,
            reasoning=draft.reasoning,
            evidence_summary=draft.evidence_summary,
            fine_amount_inr=draft.fine_amount_inr,
            draft_notice=draft.draft_notice,
            language=event.citizen_language,
            confidence=draft.confidence,
        )
        challan_id = db.insert_challan(record, db_path=db_path)  # forces pending_review
        log.info("Enforcement drafted challan #%d for %s (valid=%s)",
                 challan_id, event.plate, draft.is_valid_violation)
        return challan_id, draft
