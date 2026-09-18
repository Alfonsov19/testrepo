"""Business-lookup tests against a temporary database. No network."""
from __future__ import annotations

import pytest

from app.business import lookup, normalise_weight, resolve_country
from app.db import bootstrap, connect
from app.models import ExtractedFacts


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "test.db")
    bootstrap(path, seed=True)
    return path


@pytest.mark.parametrize(
    "weight,unit,expected",
    [(10, "kg", 10.0), (40, "lb", 18.144), (30, "libras", 13.608),
     (None, "kg", None), (10, None, None), (-5, "kg", None), (10, "stone", None)],
)
def test_normalise_weight(weight, unit, expected):
    assert normalise_weight(weight, unit) == expected


def test_resolve_country_is_case_insensitive_and_rejects_unknown(db):
    with connect(db) as conn:
        assert resolve_country(conn, "colombia") == "Colombia"
        assert resolve_country(conn, "Atlantis") is None
        assert resolve_country(conn, None) is None


def test_lookup_finds_rate_for_known_country_and_weight(db):
    facts = ExtractedFacts(destination_country="Colombia", weight=40, weight_unit="lb")
    data = lookup(facts, needs_pricing=True, needs_restrictions=False, db_path=db)
    assert data.country_supported is True
    assert data.rate is not None and data.rate["currency"] == "CAD"
    assert data.rate["weight_kg"] == 18.144


def test_lookup_without_weight_returns_no_rate(db):
    facts = ExtractedFacts(destination_country="Colombia")
    data = lookup(facts, needs_pricing=True, needs_restrictions=False, db_path=db)
    assert data.rate is None
    assert any("weight missing" in n for n in data.notes)


def test_lookup_unknown_country_is_not_supported(db):
    facts = ExtractedFacts(destination_country="Atlantis")
    data = lookup(facts, needs_pricing=True, needs_restrictions=False, db_path=db)
    assert data.country_supported is False
    assert data.rate is None


def test_lookup_returns_restrictions_only_when_asked(db):
    facts = ExtractedFacts(destination_country="Mexico")
    assert lookup(facts, False, True, db_path=db).restrictions
    assert lookup(facts, False, False, db_path=db).restrictions == []


def test_weight_over_all_bands_yields_no_rate(db):
    facts = ExtractedFacts(destination_country="Colombia", weight=900, weight_unit="kg")
    data = lookup(facts, needs_pricing=True, needs_restrictions=False, db_path=db)
    assert data.rate is None
    assert any("no rate band" in n for n in data.notes)
