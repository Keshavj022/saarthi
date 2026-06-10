"""SQLite store for enforcement challans (stdlib sqlite3).

Challans are ALWAYS created with status ``pending_review`` — Saarthi never
auto-issues a citation. A human officer approves or rejects each one. The DB
lives at `settings.db_path` (gitignored); tests pass a temporary path.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from config.settings import settings

log = logging.getLogger(__name__)

PENDING = "pending_review"
VALID_STATUSES = {PENDING, "approved", "rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS challans (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    plate              TEXT    NOT NULL,
    violation_type     TEXT    NOT NULL,
    junction_id        TEXT,
    timestamp          TEXT,
    is_valid_violation INTEGER,
    reasoning          TEXT,
    evidence_summary   TEXT,
    fine_amount_inr    INTEGER,
    draft_notice       TEXT,
    language           TEXT,
    confidence         REAL,
    status             TEXT    NOT NULL DEFAULT 'pending_review',
    created_at         TEXT    DEFAULT (datetime('now'))
);
"""

_COLUMNS = [
    "plate", "violation_type", "junction_id", "timestamp", "is_valid_violation",
    "reasoning", "evidence_summary", "fine_amount_inr", "draft_notice",
    "language", "confidence", "status",
]


@contextmanager
def _conn(db_path: Optional[str | Path] = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path) if db_path else settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(db_path: Optional[str | Path] = None) -> None:
    with _conn(db_path) as con:
        con.executescript(_SCHEMA)


def insert_challan(record: dict, db_path: Optional[str | Path] = None) -> int:
    """Insert a challan; forces status to 'pending_review' (never auto-issued)."""
    init_db(db_path)
    row = {k: record.get(k) for k in _COLUMNS}
    row["status"] = PENDING  # hard guarantee: human-in-the-loop
    if isinstance(row["is_valid_violation"], bool):
        row["is_valid_violation"] = int(row["is_valid_violation"])
    placeholders = ", ".join(f":{c}" for c in _COLUMNS)
    cols = ", ".join(_COLUMNS)
    with _conn(db_path) as con:
        cur = con.execute(f"INSERT INTO challans ({cols}) VALUES ({placeholders})", row)
        challan_id = cur.lastrowid
    log.info("Challan #%d drafted for plate %s (status=%s)", challan_id,
             row["plate"], PENDING)
    return challan_id


def list_challans(status: Optional[str] = None,
                  db_path: Optional[str | Path] = None) -> list[dict]:
    init_db(db_path)
    query = "SELECT * FROM challans"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY id DESC"
    with _conn(db_path) as con:
        return [dict(r) for r in con.execute(query, params).fetchall()]


def get_challan(challan_id: int, db_path: Optional[str | Path] = None) -> Optional[dict]:
    init_db(db_path)
    with _conn(db_path) as con:
        row = con.execute("SELECT * FROM challans WHERE id = ?", (challan_id,)).fetchone()
    return dict(row) if row else None


def update_status(challan_id: int, status: str,
                  db_path: Optional[str | Path] = None) -> None:
    """Officer action: approve/reject a pending challan."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}; must be one of {VALID_STATUSES}")
    with _conn(db_path) as con:
        con.execute("UPDATE challans SET status = ? WHERE id = ?", (status, challan_id))
