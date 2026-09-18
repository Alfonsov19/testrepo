"""Business-data lookup. The database is the source of truth for company facts.

Extracted values are validated here before they touch a query: a country must
exist in `countries`, a weight must be a positive number, and weights are
normalised to kilograms. Anything that fails validation is treated as missing,
which routes the inquiry to review rather than answering from a bad value.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date
from typing import Any

from app.db import connect
from app.models import BusinessData, ExtractedFacts

logger = logging.getLogger(__name__)

_LB_PER_KG = 0.45359237
_WEIGHT_UNITS = {
    "kg": 1.0, "kgs": 1.0, "kilo": 1.0, "kilos": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "lb": _LB_PER_KG, "lbs": _LB_PER_KG, "pound": _LB_PER_KG, "pounds": _LB_PER_KG,
    "libra": _LB_PER_KG, "libras": _LB_PER_KG,
}
DEFAULT_SERVICE = "standard_parcel"


def normalise_weight(weight: float | None, unit: str | None) -> float | None:
    """Convert to kilograms. Returns None if unusable - never a guessed value."""
    if weight is None or weight <= 0:
        return None
    if unit is None:
        return None  # ambiguous: do not assume a unit
    factor = _WEIGHT_UNITS.get(unit.strip().lower())
    if factor is None:
        logger.info("unrecognised weight unit %r", unit)
        return None
    return round(weight * factor, 3)


def resolve_country(conn: sqlite3.Connection, name: str | None) -> str | None:
    """Return the canonical country name, or None if we do not serve/know it."""
    if not name:
        return None
    row = conn.execute(
        "SELECT name FROM countries WHERE lower(name) = lower(?) AND active = 1",
        (name.strip(),),
    ).fetchone()
    return row["name"] if row else None


def _find_service(conn, country: str, service_type: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, destination_country, service_type, transit_time_text "
        "FROM services WHERE destination_country = ? AND service_type = ? AND active = 1",
        (country, service_type),
    ).fetchone()
    return dict(row) if row else None


def _find_rate(conn, service_id: int, weight_kg: float) -> dict[str, Any] | None:
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT price, currency, min_weight, max_weight FROM rates "
        "WHERE service_id = ? AND ? > min_weight AND ? <= max_weight "
        "  AND effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?) "
        "ORDER BY min_weight LIMIT 1",
        (service_id, weight_kg, weight_kg, today, today),
    ).fetchone()
    return dict(row) if row else None


def _find_restrictions(conn, country: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT category, rule_text FROM restrictions "
        "WHERE destination_country = ? AND active = 1",
        (country,),
    ).fetchall()
    return [dict(r) for r in rows]


def _business_info(conn) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM business_info")}


def lookup(
    facts: ExtractedFacts,
    needs_pricing: bool,
    needs_restrictions: bool,
    db_path: str | None = None,
) -> BusinessData:
    """Fetch only the verified data this inquiry needs. Missing stays missing."""
    notes: list[str] = []
    with connect(db_path) as conn:
        info = _business_info(conn)
        country = resolve_country(conn, facts.destination_country)
        if facts.destination_country and not country:
            notes.append(f"destination '{facts.destination_country}' not in active countries")
        if not country:
            return BusinessData(
                country_supported=False if facts.destination_country else None,
                business_info=info,
                notes=notes or ["no destination country identified"],
            )

        service_type = facts.service_type or DEFAULT_SERVICE
        service = _find_service(conn, country, service_type)
        if service is None:
            notes.append(f"no active '{service_type}' service for {country}")

        rate = None
        if needs_pricing:
            weight_kg = normalise_weight(facts.weight, facts.weight_unit)
            if weight_kg is None:
                notes.append("weight missing or not usable - cannot match a rate")
            elif service is not None:
                rate = _find_rate(conn, service["id"], weight_kg)
                if rate is None:
                    notes.append(f"no rate band covers {weight_kg} kg for {country}")
                else:
                    rate = {**rate, "weight_kg": weight_kg}

        restrictions = _find_restrictions(conn, country) if needs_restrictions else []
        if needs_restrictions and not restrictions:
            notes.append(f"no restriction records for {country}")

        return BusinessData(
            country_supported=True,
            service=service,
            rate=rate,
            restrictions=restrictions,
            business_info=info,
            notes=notes,
        )
