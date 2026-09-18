"""Shadow-mode instrumentation tests. Deterministic, no network, no model calls."""
from __future__ import annotations

import json

import pytest

from app.db import bootstrap, connect
from app.models import BusinessData, ExtractedFacts
from app.shadow import (bootstrap_shadow, contradictions, missing_facts, record,
                        save_human_evaluation, unsupported_facts)

RATE = {"price": 49.0, "currency": "CAD", "min_weight": 0.0, "max_weight": 25.0, "weight_kg": 18.144}
SERVICE_T = {"id": 1, "destination_country": "Colombia", "service_type": "standard_parcel",
             "transit_time_text": "TEST DATA: approx. 7-10 business days"}
SERVICE_NO_T = {**SERVICE_T, "transit_time_text": None}
FULL = BusinessData(country_supported=True, service=SERVICE_T, rate=RATE)
NO_RATE = BusinessData(country_supported=True, service=SERVICE_T, rate=None)
NOTHING = BusinessData()


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "shadow.db")
    bootstrap(path, seed=True)
    bootstrap_shadow(path)
    return path


# --- unsupported facts -----------------------------------------------------

def test_verified_price_is_supported():
    assert unsupported_facts("It is $49.00 CAD.", FULL, "") == []


def test_price_with_no_verified_rate_is_flagged():
    found = unsupported_facts("It is $49.00 CAD.", NO_RATE, "")
    assert [f["category"] for f in found] == ["price"]


def test_invented_price_is_flagged_even_when_a_rate_exists():
    found = unsupported_facts("It is $75.00 CAD.", FULL, "")
    assert any(f["category"] == "price" for f in found)


def test_verified_transit_time_is_supported():
    assert unsupported_facts("About 7-10 business days.", FULL, "") == []


def test_transit_time_with_none_verified_is_flagged():
    b = BusinessData(country_supported=True, service=SERVICE_NO_T, rate=RATE)
    found = unsupported_facts("About 7-10 business days.", b, "")
    assert [f["category"] for f in found] == ["transit_time"]


@pytest.mark.parametrize("phrase", [
    "Your parcel cleared customs yesterday.",
    "It is currently in Bogota.",
    "It is out for delivery.",
    "It will arrive on Friday.",
])
def test_tracking_or_customs_status_is_always_flagged(phrase):
    found = unsupported_facts(phrase, NOTHING, "")
    assert any(f["category"] == "tracking_or_customs_status" for f in found)


def test_invented_policy_is_flagged_when_no_restrictions_verified():
    found = unsupported_facts("Lithium batteries are prohibited.", NOTHING, "")
    assert any(f["category"] == "policy_or_availability" for f in found)


def test_clean_deferral_draft_flags_nothing():
    draft = ("I don't have a verified price on hand, so I'm passing your question "
             "to a colleague who can confirm.")
    assert unsupported_facts(draft, NOTHING, "") == []


def test_customer_supplied_numbers_do_not_count_as_invention():
    assert unsupported_facts("Your 40 lb box", NOTHING, "I have a 40 lb box") == []


# --- missing facts ---------------------------------------------------------

def test_missing_fact_when_verified_rate_unused():
    assert "verified rate available but not stated" in missing_facts("We can help.", FULL)


def test_no_missing_fact_when_draft_uses_the_data():
    assert missing_facts("It is $49.00 CAD, about 7-10 business days.", FULL) == []


# --- contradictions --------------------------------------------------------

def test_destination_not_in_message_is_a_contradiction():
    out = contradictions(ExtractedFacts(destination_country="Venezuela"), FULL, "shipping to Colombia")
    assert any("does not appear" in c for c in out)


def test_unserved_destination_is_a_contradiction():
    out = contradictions(ExtractedFacts(destination_country="Atlantis"),
                         BusinessData(country_supported=False), "ship to Atlantis")
    assert any("not an active served country" in c for c in out)


def test_consistent_extraction_has_no_contradiction():
    out = contradictions(ExtractedFacts(destination_country="Colombia", weight=40.0),
                         FULL, "send a 40 lb box to Colombia")
    assert out == []


# --- persistence + the never-send invariant --------------------------------

def _seed_inquiry(db) -> int:
    from app.logging_store import add_message, create_conversation, record_inquiry
    from app.models import RoutingDecision, Signals
    with connect(db) as conn:
        cid = create_conversation(conn)
        mid = add_message(conn, cid, "inbound", "test")
        iid = record_inquiry(conn, mid, Signals(), ExtractedFacts(), NOTHING,
                             RoutingDecision("AUTO", []), "draft", 10)
        conn.commit()
    return iid


def test_shadow_record_round_trips_and_never_sets_sent(db):
    iid = _seed_inquiry(db)
    with connect(db) as conn:
        sid, flags = record(conn, iid, ExtractedFacts(destination_country="Colombia"),
                            FULL, "It is $49.00 CAD.", "ship to Colombia", source_ref="TICKET-1")
        conn.commit()
        row = dict(conn.execute("SELECT * FROM shadow_records WHERE id = ?", (sid,)).fetchone())
        inq = dict(conn.execute("SELECT sent FROM inquiries WHERE id = ?", (iid,)).fetchone())
    assert row["source_ref"] == "TICKET-1"
    assert json.loads(row["extracted_facts"])["destination_country"] == "Colombia"
    assert json.loads(row["verified_business_data_used"])["rate"]["price"] == 49.0
    assert row["unsupported_fact_detected"] == 0
    assert row["human_would_approve_without_edit"] is None  # only a human fills this
    assert inq["sent"] == 0, "SHADOW_ONLY: sent must remain 0"


def test_flags_are_persisted_when_a_draft_invents_a_price(db):
    iid = _seed_inquiry(db)
    with connect(db) as conn:
        sid, flags = record(conn, iid, ExtractedFacts(), NO_RATE, "It is $49.00 CAD.", "hi")
        conn.commit()
        row = dict(conn.execute("SELECT * FROM shadow_records WHERE id = ?", (sid,)).fetchone())
    assert row["unsupported_fact_detected"] == 1
    assert json.loads(row["unsupported_fact_detail"])[0]["category"] == "price"


def test_human_evaluation_is_stored_separately(db):
    iid = _seed_inquiry(db)
    with connect(db) as conn:
        sid, _ = record(conn, iid, ExtractedFacts(), FULL, "draft", "msg")
        conn.commit()
    assert save_human_evaluation(sid, "agent_a", {
        "actual_human_response": "what the agent really sent",
        "human_would_approve_without_edit": 0, "human_edit_required": 1,
        "edit_reason": "too_verbose", "appropriate_tone": 1}, db_path=db)
    with connect(db) as conn:
        row = dict(conn.execute("SELECT * FROM shadow_records WHERE id = ?", (sid,)).fetchone())
    assert row["edit_reason"] == "too_verbose"
    assert row["evaluator"] == "agent_a"
    assert row["human_would_approve_without_edit"] == 0


def test_shadow_module_contains_no_path_that_sets_sent_true():
    src = open("app/shadow.py").read()
    assert "sent = 1" not in src and "sent=1" not in src
