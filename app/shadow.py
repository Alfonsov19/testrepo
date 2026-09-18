"""Shadow-mode pilot instrumentation.

Runs the existing V1 pipeline over real inquiries and records everything needed
to evaluate it, WITHOUT ever sending a customer message.

Nothing here changes routing, thresholds, prompts or signal definitions. It adds
observation only: the pilot-only fields, automated safety flags, and a slot for
human evaluation that only a person fills in.

SHADOW_ONLY invariant: `sent` is written 0 and this module contains no code path
that sets it to 1. AUTO here means "would have been eligible for automation",
never "send".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import connect
from app.models import BusinessData, ExtractedFacts

logger = logging.getLogger(__name__)
_SHADOW_SCHEMA = Path(__file__).with_name("shadow_schema.sql")

# Tokens that assert a business fact. Used to detect claims a draft should not
# make when the verified-data object does not support them.
_MONEY = re.compile(r"(?:\$|\bCAD\b|\bUSD\b)\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*(?:CAD|USD)\b", re.I)
_DURATION = re.compile(r"\b\d+(?:\s*[-–]\s*\d+)?\s*(?:business\s+)?(?:day|days|week|weeks|month|months|hour|hours)\b", re.I)
_TRACKING = re.compile(
    r"\b(?:currently (?:in|at)|cleared customs|in customs|held at|arrived at|departed|"
    r"out for delivery|last scan(?:ned)?|in transit (?:in|at|through)|will (?:arrive|be delivered) on)\b",
    re.I,
)
_POLICY = re.compile(
    r"\b(?:we (?:do not|don'?t) (?:ship|allow|accept|permit)|"
    r"(?:is|are|was|were) (?:prohibited|banned|not permitted|not allowed|restricted)|"
    r"(?:cannot|can'?t|may not) be (?:shipped|sent|mailed)|"
    r"our policy (?:is|states)|we (?:guarantee|always|never))\b",
    re.I,
)


def bootstrap_shadow(db_path: str | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(_SHADOW_SCHEMA.read_text())
        conn.commit()


def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for tok in re.findall(r"\d+(?:[.,]\d+)?", text or ""):
        try:
            out.add(float(tok.replace(",", ".")))
        except ValueError:
            pass
    return out


def unsupported_facts(draft: str, business: BusinessData, customer_message: str) -> list[dict[str, Any]]:
    """Business claims in the draft that the verified data does not support.

    Numbers are compared numerically, so 49.00 matches a verified 49.0. Values
    derived from verified data (a rounded unit conversion) still surface here
    and need human adjudication - that is deliberate.
    """
    if not draft:
        return []
    verified_json = json.dumps(business.as_dict(), ensure_ascii=False)
    supported = _numbers(verified_json) | _numbers(customer_message)
    findings: list[dict[str, Any]] = []

    has_rate = business.rate is not None
    for tok in set(_MONEY.findall(draft)):
        if not has_rate or not (_numbers(tok) <= supported):
            findings.append({"category": "price", "token": tok.strip()})

    transit = (business.service or {}).get("transit_time_text")
    for tok in set(_DURATION.findall(draft)):
        if not transit or not (_numbers(tok) <= supported):
            findings.append({"category": "transit_time", "token": tok.strip()})

    for tok in set(_TRACKING.findall(draft)):
        findings.append({"category": "tracking_or_customs_status", "token": tok.strip()})

    if not business.restrictions:
        for tok in set(_POLICY.findall(draft)):
            findings.append({"category": "policy_or_availability", "token": tok.strip()})

    return findings


def missing_facts(draft: str, business: BusinessData) -> list[str]:
    """Verified data we held but the draft did not use."""
    if not draft:
        return []
    out = []
    if business.rate and not _MONEY.search(draft):
        out.append("verified rate available but not stated")
    transit = (business.service or {}).get("transit_time_text")
    if transit and not _DURATION.search(draft):
        out.append("verified transit time available but not stated")
    return out


def contradictions(facts: ExtractedFacts, business: BusinessData, customer_message: str) -> list[str]:
    """Extraction conflicting with the customer's words or with verified data."""
    out: list[str] = []
    msg = (customer_message or "").lower()
    dest = facts.destination_country
    if dest and dest.lower() not in msg:
        out.append(f"extracted destination '{dest}' does not appear in the customer message")
    if dest and business.country_supported is False:
        out.append(f"extracted destination '{dest}' is not an active served country")
    if facts.weight is not None and facts.weight not in _numbers(msg):
        out.append(f"extracted weight {facts.weight} does not appear in the customer message")
    return out


def record(
    conn,
    inquiry_id: int,
    facts: ExtractedFacts,
    business: BusinessData,
    draft: str | None,
    customer_message: str,
    source_ref: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Write the shadow overlay row. Never writes `sent`."""
    uns = unsupported_facts(draft or "", business, customer_message)
    mis = missing_facts(draft or "", business)
    con = contradictions(facts, business, customer_message)
    cur = conn.execute(
        """INSERT INTO shadow_records (
               inquiry_id, source_ref, extracted_facts, verified_business_data_used,
               unsupported_fact_detected, unsupported_fact_detail,
               missing_fact_detected, missing_fact_detail,
               contradiction_detected, contradiction_detail, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (inquiry_id, source_ref,
         json.dumps(facts.as_dict(), ensure_ascii=False),
         json.dumps(business.as_dict(), ensure_ascii=False),
         int(bool(uns)), json.dumps(uns) if uns else None,
         int(bool(mis)), json.dumps(mis) if mis else None,
         int(bool(con)), json.dumps(con) if con else None,
         datetime.now(timezone.utc).isoformat()),
    )
    return int(cur.lastrowid), {"unsupported": uns, "missing": mis, "contradictions": con}


def save_human_evaluation(shadow_id: int, evaluator: str, ratings: dict[str, Any],
                          db_path: str | None = None) -> bool:
    """Store a person's rating of a draft. Ratings never come from code."""
    fields = ("actual_human_response", "human_would_approve_without_edit",
              "human_edit_required", "edit_reason", "correct_business_facts",
              "complete_enough", "correct_language", "appropriate_tone")
    sets = ", ".join(f"{f} = ?" for f in fields if f in ratings)
    if not sets:
        return False
    values = [ratings[f] for f in fields if f in ratings]
    with connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE shadow_records SET {sets}, evaluated_at = ?, evaluator = ? WHERE id = ?",
            (*values, datetime.now(timezone.utc).isoformat(), evaluator, shadow_id),
        )
        conn.commit()
        return cur.rowcount > 0
