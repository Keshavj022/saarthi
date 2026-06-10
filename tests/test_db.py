"""Tests for the SQLite challan store (no LLM)."""
from __future__ import annotations

from core.db import (PENDING, get_challan, insert_challan, list_challans,
                     update_status)


def _record(plate: str = "MH12AB1234") -> dict:
    return dict(
        plate=plate, violation_type="red_light_jump", junction_id="C",
        timestamp="t1", is_valid_violation=True, reasoning="r",
        evidence_summary="e", fine_amount_inr=1000, draft_notice="n",
        language="Hindi", confidence=0.9,
        status="approved",  # should be IGNORED and forced to pending_review
    )


def test_insert_forces_pending_review(tmp_path):
    db = tmp_path / "t.db"
    cid = insert_challan(_record(), db_path=db)
    rec = get_challan(cid, db_path=db)
    assert rec["status"] == PENDING  # never auto-issued, even if asked
    assert rec["plate"] == "MH12AB1234"
    assert rec["is_valid_violation"] == 1


def test_list_filter_and_status_update(tmp_path):
    db = tmp_path / "t.db"
    c1 = insert_challan(_record("AAA1A1111"), db_path=db)
    insert_challan(_record("BBB2B2222"), db_path=db)
    assert len(list_challans(db_path=db)) == 2
    assert len(list_challans(status=PENDING, db_path=db)) == 2

    update_status(c1, "approved", db_path=db)
    assert len(list_challans(status=PENDING, db_path=db)) == 1
    assert len(list_challans(status="approved", db_path=db)) == 1


def test_invalid_status_rejected(tmp_path):
    db = tmp_path / "t.db"
    cid = insert_challan(_record(), db_path=db)
    try:
        update_status(cid, "issued", db_path=db)
        assert False, "expected ValueError"
    except ValueError:
        pass
