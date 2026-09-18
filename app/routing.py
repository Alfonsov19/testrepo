"""The routing decision. This is the whole business rule - deliberately one
readable function with no I/O, so it can be unit-tested without network calls.

Jev never decides AUTO or REVIEW. It supplies probabilities; this code decides.
"""
from __future__ import annotations

from app import config
from app.models import BusinessData, ExtractedFacts, RoutingDecision, Signals

AUTO = "AUTO"
REVIEW = "REVIEW"


def decide(
    signals: Signals,
    facts: ExtractedFacts,
    business: BusinessData,
    threshold: float | None = None,
) -> RoutingDecision:
    """Return AUTO only when nothing needs a human and every needed fact is verified."""
    t = config.SETTINGS.signal_threshold if threshold is None else threshold
    reasons: list[str] = []

    # 1. Signals that always require a human.
    if signals.complaint >= t:
        reasons.append(f"complaint ({signals.complaint:.2f} >= {t:.2f})")
    if signals.complex_shipment >= t:
        reasons.append(f"complex_shipment ({signals.complex_shipment:.2f} >= {t:.2f})")
    if signals.shipment_specific_issue >= t:
        reasons.append(
            f"shipment_specific_issue ({signals.shipment_specific_issue:.2f} >= {t:.2f})"
        )

    # 2. Degraded inputs. A missing judgment or missing facts must not auto-reply.
    if not signals.available:
        reasons.append("jev signals unavailable")
    if not facts.available:
        reasons.append("fact extraction unavailable")

    # 3. Answers that depend on business data we must actually have.
    if signals.pricing_request >= t and business.rate is None:
        reasons.append("pricing request without a matching standard rate")
    if signals.restriction_question >= t and not business.restrictions:
        reasons.append("restriction question without restriction data")

    return RoutingDecision(REVIEW if reasons else AUTO, reasons)
