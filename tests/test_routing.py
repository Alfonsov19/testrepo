"""Routing rule tests. Pure functions only - no Jev, no Claude, no network."""
from __future__ import annotations

import pytest

from app.models import BusinessData, ExtractedFacts, Signals
from app.routing import AUTO, REVIEW, decide

T = 0.50
RATE = {"price": 49.0, "currency": "CAD", "min_weight": 0.0, "max_weight": 25.0}
RESTRICTIONS = [{"category": "electronics", "rule_text": "TEST DATA: one phone."}]
FACTS = ExtractedFacts(destination_country="Colombia", weight=10.0, weight_unit="kg")
NO_DATA = BusinessData()


def test_complaint_always_routes_review():
    d = decide(Signals(complaint=0.99), FACTS, BusinessData(rate=RATE), threshold=T)
    assert d.decision == REVIEW
    assert any("complaint" in r for r in d.reasons)


def test_complex_shipment_always_routes_review():
    d = decide(Signals(complex_shipment=0.82), FACTS, BusinessData(rate=RATE), threshold=T)
    assert d.decision == REVIEW
    assert any("complex_shipment" in r for r in d.reasons)


def test_shipment_specific_issue_always_routes_review():
    d = decide(
        Signals(shipment_specific_issue=0.97), FACTS, BusinessData(rate=RATE), threshold=T
    )
    assert d.decision == REVIEW
    assert any("shipment_specific_issue" in r for r in d.reasons)


def test_pricing_request_with_matching_rate_can_auto():
    d = decide(
        Signals(sales_lead=0.97, pricing_request=0.99),
        FACTS,
        BusinessData(country_supported=True, rate=RATE),
        threshold=T,
    )
    assert d.decision == AUTO, d.reasons


def test_pricing_request_without_matching_rate_routes_review():
    d = decide(
        Signals(sales_lead=0.97, pricing_request=0.99),
        FACTS,
        BusinessData(country_supported=True, rate=None),
        threshold=T,
    )
    assert d.decision == REVIEW
    assert any("without a matching standard rate" in r for r in d.reasons)


def test_restriction_request_without_database_information_routes_review():
    d = decide(
        Signals(sales_lead=0.90, restriction_question=0.95),
        FACTS,
        BusinessData(country_supported=True, restrictions=[]),
        threshold=T,
    )
    assert d.decision == REVIEW
    assert any("without restriction data" in r for r in d.reasons)


def test_restriction_request_with_database_information_can_auto():
    d = decide(
        Signals(sales_lead=0.90, restriction_question=0.95),
        FACTS,
        BusinessData(country_supported=True, restrictions=RESTRICTIONS),
        threshold=T,
    )
    assert d.decision == AUTO, d.reasons


def test_simple_general_inquiry_can_auto():
    d = decide(Signals(sales_lead=0.78), ExtractedFacts(), NO_DATA, threshold=T)
    assert d.decision == AUTO, d.reasons


# --- fail-safe behaviour ---------------------------------------------------

def test_unavailable_signals_route_review():
    d = decide(Signals(available=False), FACTS, NO_DATA, threshold=T)
    assert d.decision == REVIEW
    assert "jev signals unavailable" in d.reasons


def test_unavailable_extraction_routes_review():
    d = decide(Signals(sales_lead=0.9), ExtractedFacts(available=False), NO_DATA, threshold=T)
    assert d.decision == REVIEW
    assert "fact extraction unavailable" in d.reasons


def test_all_review_reasons_are_reported_not_just_the_first():
    d = decide(
        Signals(complaint=0.99, complex_shipment=0.99, shipment_specific_issue=0.99),
        FACTS, NO_DATA, threshold=T,
    )
    assert len(d.reasons) == 3


@pytest.mark.parametrize("value,expected", [(0.49, AUTO), (0.50, REVIEW), (0.51, REVIEW)])
def test_threshold_is_inclusive_at_the_boundary(value, expected):
    assert decide(Signals(complaint=value), FACTS, NO_DATA, threshold=T).decision == expected
