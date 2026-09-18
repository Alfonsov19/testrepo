"""End-to-end pipeline tests through the HTTP endpoint.

Jev and Claude are stubbed so the wiring (signals -> facts -> lookup -> routing
-> persistence) is exercised deterministically and without network calls.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, logging_store, main
from app.config import Settings
from app.db import bootstrap
from app.models import ExtractedFacts, Signals


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Point every module at a throwaway database and stubbed credentials.

    Modules read `config.SETTINGS` at call time, so replacing the attribute
    here is enough - no per-module patching needed.
    """
    db = str(tmp_path / "pipeline.db")
    bootstrap(db, seed=True)
    replacement = Settings(
        jev_model="jev-1.13.0", claude_model="claude-opus-5",
        typesafe_base_url="https://api.typesafe.ai", typesafe_api_key="stub",
        anthropic_api_key="stub", db_path=db, signal_threshold=0.50,
    )
    monkeypatch.setattr(config, "SETTINGS", replacement)
    return replacement


@pytest.fixture()
def client(settings):
    with TestClient(main.app) as c:
        yield c


def _stub(monkeypatch, signals: Signals, facts: ExtractedFacts, draft="DRAFT"):
    monkeypatch.setattr(main.jev, "get_signals", lambda _t: signals)
    monkeypatch.setattr(main.claude_client, "extract_facts", lambda _t: facts)
    monkeypatch.setattr(main.claude_client, "draft_response", lambda **_k: draft)


def test_pricing_inquiry_with_matching_rate_routes_auto(client, monkeypatch):
    _stub(monkeypatch,
          Signals(sales_lead=0.97, pricing_request=0.99, model="jev-1.13.0"),
          ExtractedFacts(destination_country="Colombia", weight=40, weight_unit="lb",
                         language="en"))
    body = client.post("/messages", json={"customer_message": "How much for 40 lb to Colombia?"}).json()
    assert body["routing_decision"] == "AUTO", body["routing_reason"]
    assert body["verified_business_data"]["rate"]["price"] == 49.0  # 40 lb = 18.14 kg -> 0-25 kg band
    assert body["verified_business_data"]["rate"]["weight_kg"] == 18.144
    assert body["suggested_response"] == "DRAFT"
    assert body["inquiry_id"] >= 1


def test_complaint_routes_review_even_with_a_rate(client, monkeypatch):
    _stub(monkeypatch,
          Signals(complaint=0.99, pricing_request=0.99, model="jev-1.13.0"),
          ExtractedFacts(destination_country="Colombia", weight=10, weight_unit="kg"))
    body = client.post("/messages", json={"customer_message": "late and I am angry"}).json()
    assert body["routing_decision"] == "REVIEW"
    assert "complaint" in body["routing_reason"]


def test_inquiry_is_persisted_with_probabilities_and_timing(client, settings, monkeypatch):
    _stub(monkeypatch,
          Signals(sales_lead=0.9, complaint=0.77, model="jev-1.13.0"),
          ExtractedFacts(destination_country="Mexico", language="es"))
    inquiry_id = client.post("/messages", json={"customer_message": "hola"}).json()["inquiry_id"]
    row = logging_store.get_inquiry(inquiry_id, db_path=settings.db_path)
    assert row["complaint_probability"] == 0.77
    assert row["destination_country"] == "Mexico"
    assert row["language"] == "es"
    assert row["jev_model"] == "jev-1.13.0"
    assert row["routing_decision"] == "REVIEW"
    assert row["processing_ms"] >= 0
    assert row["human_reviewed"] == 0 and row["sent"] == 0


def test_review_queue_approve_and_edit_flow(client, settings, monkeypatch):
    _stub(monkeypatch, Signals(complaint=0.99), ExtractedFacts())
    inquiry_id = client.post("/messages", json={"customer_message": "problem"}).json()["inquiry_id"]
    assert client.get("/review").json()["count"] == 1
    client.post(f"/review/{inquiry_id}/edit", json={"text": "edited"})
    row = logging_store.get_inquiry(inquiry_id, db_path=settings.db_path)
    assert row["human_edited"] == 1 and row["generated_response"] == "edited"
    client.post(f"/review/{inquiry_id}/approve")
    assert client.get("/review").json()["count"] == 0
    assert client.post("/review/424242/approve").status_code == 404


def test_empty_message_is_rejected(client):
    assert client.post("/messages", json={"customer_message": "   "}).status_code == 422
