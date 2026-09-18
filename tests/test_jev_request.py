"""Jev request-shape tests. Builds the body only - makes no API call."""
from __future__ import annotations

from app.jev import QUESTIONS, build_request


def test_state_contains_only_the_customer_message():
    body = build_request("How much to ship 40 lb to Colombia?")
    assert list(body["state"]) == ["customer_message"]


def test_model_is_pinned_not_an_alias():
    assert build_request("hi")["model"] == "jev-1.13.0"


def test_seven_independent_noul_questions():
    body = build_request("hi")
    assert len(body["questions"]) == 7 == len(QUESTIONS)
    assert all(q["type"] == "noul" for q in body["questions"].values())
    assert all(set(q) == {"type", "instructions"} for q in body["questions"].values())
