"""Shared dataclasses. Plain data, no behaviour."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

SIGNAL_NAMES: tuple[str, ...] = (
    "sales_lead",
    "pricing_request",
    "tracking_request",
    "restriction_question",
    "complaint",
    "complex_shipment",
    "shipment_specific_issue",
)


@dataclass(frozen=True)
class Signals:
    """Raw Jev probabilities, one per signal. Booleans are derived, not stored."""

    sales_lead: float = 0.0
    pricing_request: float = 0.0
    tracking_request: float = 0.0
    restriction_question: float = 0.0
    complaint: float = 0.0
    complex_shipment: float = 0.0
    shipment_specific_issue: float = 0.0
    model: str | None = None
    available: bool = True

    def booleans(self, threshold: float) -> dict[str, bool]:
        return {n: getattr(self, n) >= threshold for n in SIGNAL_NAMES}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExtractedFacts:
    """Facts pulled from the message. Every field may be missing."""

    origin_country_or_city: str | None = None
    destination_country: str | None = None
    weight: float | None = None
    weight_unit: str | None = None
    service_type: str | None = None
    language: str | None = None
    items_mentioned: list[str] = field(default_factory=list)
    available: bool = True
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BusinessData:
    """Verified facts read from the business database. Authoritative."""

    country_supported: bool | None = None
    service: dict[str, Any] | None = None
    rate: dict[str, Any] | None = None
    restrictions: list[dict[str, Any]] = field(default_factory=list)
    business_info: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RoutingDecision:
    decision: str  # "AUTO" | "REVIEW"
    reasons: list[str]

    @property
    def reason_text(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "no review condition met"
