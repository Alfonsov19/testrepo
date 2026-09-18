"""Persistence for the interaction log. Every inquiry is stored as structured
data so the analytics questions can be answered later with plain SQL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import connect
from app.models import BusinessData, ExtractedFacts, RoutingDecision, Signals


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_conversation(conn, customer_reference: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO conversations (created_at, customer_reference) VALUES (?, ?)",
        (_now(), customer_reference),
    )
    return int(cur.lastrowid)


def add_message(conn, conversation_id: int, direction: str, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, direction, text, created_at) VALUES (?, ?, ?, ?)",
        (conversation_id, direction, text, _now()),
    )
    return int(cur.lastrowid)


def record_inquiry(
    conn,
    message_id: int,
    signals: Signals,
    facts: ExtractedFacts,
    business: BusinessData,
    routing: RoutingDecision,
    draft: str | None,
    processing_ms: int,
) -> int:
    cur = conn.execute(
        """INSERT INTO inquiries (
               message_id, destination_country, language,
               sales_lead_probability, pricing_request_probability,
               tracking_request_probability, restriction_question_probability,
               complaint_probability, complex_shipment_probability,
               shipment_specific_issue_probability,
               routing_decision, routing_reason, generated_response,
               human_reviewed, human_edited, sent, jev_model, processing_ms, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?,?)""",
        (
            message_id,
            facts.destination_country,
            facts.language,
            signals.sales_lead,
            signals.pricing_request,
            signals.tracking_request,
            signals.restriction_question,
            signals.complaint,
            signals.complex_shipment,
            signals.shipment_specific_issue,
            routing.decision,
            routing.reason_text,
            draft,
            signals.model,
            processing_ms,
            _now(),
        ),
    )
    return int(cur.lastrowid)


def pending_review(db_path: str | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT i.*, m.text AS customer_message
               FROM inquiries i JOIN messages m ON m.id = i.message_id
               WHERE i.routing_decision = 'REVIEW' AND i.human_reviewed = 0
               ORDER BY i.created_at""",
        ).fetchall()
    return [dict(r) for r in rows]


def get_inquiry(inquiry_id: int, db_path: str | None = None) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM inquiries WHERE id = ?", (inquiry_id,)).fetchone()
    return dict(row) if row else None


def approve(inquiry_id: int, db_path: str | None = None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE inquiries SET human_reviewed = 1, sent = 1 WHERE id = ?", (inquiry_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def save_edit(inquiry_id: int, text: str, db_path: str | None = None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE inquiries SET generated_response = ?, human_reviewed = 1, human_edited = 1 "
            "WHERE id = ?",
            (text, inquiry_id),
        )
        conn.commit()
        return cur.rowcount > 0
