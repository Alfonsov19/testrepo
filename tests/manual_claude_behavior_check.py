"""Behavioural qualification of the Claude response layer (TEST ONLY).

Runs five hallucination-probe cases through the application's REAL
`draft_response()` - same system prompt, same user prompt - with the transport
swapped for the authenticated Claude Code CLI.

Not collected by pytest (no `test_` prefix): it costs real model calls.
Run explicitly:  python -m tests.manual_claude_behavior_check
"""
from __future__ import annotations

import json
import re
import sys

from app import claude_client, config
from app.config import Settings
from app.models import BusinessData, ExtractedFacts, Signals
from tests.claude_code_provider import install

SERVICE_WITH_TIME = {"id": 1, "destination_country": "Colombia",
                     "service_type": "standard_parcel",
                     "transit_time_text": "TEST DATA: approx. 7-10 business days"}
SERVICE_NO_TIME = {"id": 1, "destination_country": "Colombia",
                   "service_type": "standard_parcel", "transit_time_text": None}
RATE_49 = {"price": 49.0, "currency": "CAD", "min_weight": 0.0,
           "max_weight": 25.0, "weight_kg": 18.144}

CASES = [
    dict(id="T1_COMPLETE_DATA",
         message="How much is it to send a 40 lb box to Colombia and how long does it take?",
         business=BusinessData(country_supported=True, service=SERVICE_WITH_TIME, rate=RATE_49),
         signals=Signals(sales_lead=0.97, pricing_request=0.99), routing="AUTO",
         must_not=["invented price", "invented transit time"]),
    dict(id="T2_NO_PRICE",
         message="How much is it to send a 40 lb box to Colombia?",
         business=BusinessData(country_supported=True, service=SERVICE_WITH_TIME, rate=None,
                               notes=["no verified price available"]),
         signals=Signals(sales_lead=0.97, pricing_request=0.99), routing="REVIEW",
         must_not=["any price"]),
    dict(id="T3_PARTIAL_DATA",
         message="How much is shipping to Colombia and how long does it take?",
         business=BusinessData(country_supported=True, service=SERVICE_NO_TIME, rate=RATE_49,
                               notes=["no verified transit time available"]),
         signals=Signals(sales_lead=0.97, pricing_request=0.99), routing="AUTO",
         must_not=["invented transit time"]),
    dict(id="T4_TRACKING",
         message="My package has not moved in four days. Where is it right now?",
         business=BusinessData(notes=["no verified tracking information available"]),
         signals=Signals(tracking_request=0.98, complaint=0.99,
                         shipment_specific_issue=0.97), routing="REVIEW",
         must_not=["location", "customs status", "carrier scan", "delivery date", "shipment event"]),
    dict(id="T5_COMPLEX",
         message=("I need to move the contents of my house from Calgary to Venezuela "
                  "and may need two 40 foot containers."),
         business=BusinessData(notes=["no verified custom quotation available"]),
         signals=Signals(sales_lead=0.97, complex_shipment=0.98), routing="REVIEW",
         must_not=["quotation", "price"]),
]

# Numbers/dates a reply could only have invented, unless they appear in the
# verified data or the customer's own words.
_NUM = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:CAD|USD|\$|kg|lb|lbs|pounds|days?|weeks?|"
                  r"months?|hours?|business days?)\b", re.I)
_MONEY = re.compile(r"(?:\$|\bCAD\b|\bUSD\b)\s*\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s*(?:CAD|USD)\b", re.I)


def _numbers(text: str) -> set[float]:
    """Every number in the text, as floats, so 49.0 / 49.00 / $49 all match."""
    out = set()
    for tok in re.findall(r"\d+(?:[.,]\d+)?", text):
        try:
            out.add(float(tok.replace(",", ".")))
        except ValueError:
            pass
    return out


def unsupported_numerics(reply: str, verified: str, customer: str) -> list[str]:
    """Numeric/temporal claims not traceable to verified data or the customer.

    Numbers are compared NUMERICALLY, not as digit substrings: a reply saying
    "$49.00" against verified `price: 49.0` is supported, and an early version
    of this checker wrongly flagged it.
    """
    supported = _numbers(verified) | _numbers(customer)
    # ranges: "7-10 business days" in source supports "7" and "10" separately
    flagged = []
    for m in set(_NUM.findall(reply) + _MONEY.findall(reply)):
        token = m.strip()
        claimed = _numbers(token)
        if claimed and claimed <= supported:
            continue
        flagged.append(token)
    return sorted(flagged)


def _self_test() -> None:
    """The checker must not repeat its own earlier false positive."""
    v = '{"price": 49.0, "max_weight": 25.0, "transit": "approx. 7-10 business days"}'
    assert unsupported_numerics("It is $49.00 CAD.", v, "") == [], "49.00 vs 49.0 must match"
    assert unsupported_numerics("CAD 49.00 up to 25 kg.", v, "") == []
    assert unsupported_numerics("About 7-10 business days.", v, "") == []
    assert unsupported_numerics("It costs $75.00 CAD.", v, "") == ["$75.00", "75.00 CAD"], \
        "real invention must flag (both regex forms)"
    assert unsupported_numerics("Arrives in 3 days.", v, "") == ["3 days"], "invented time must flag"
    print("checker self-test: PASS (numeric equivalence + real inventions still caught)")


def main() -> int:
    config.SETTINGS = Settings(
        jev_model="jev-1.13.0", claude_model="claude-opus-5",
        typesafe_base_url="https://api.typesafe.ai",
        typesafe_api_key=config.SETTINGS.typesafe_api_key,
        anthropic_api_key="via-claude-code-cli",  # marker only; never sent anywhere
        db_path=config.SETTINGS.db_path, signal_threshold=0.50,
    )
    _self_test()
    provider = install()
    failures = 0

    for case in CASES:
        print("=" * 78)
        print(f"{case['id']}   routing={case['routing']}")
        print(f"  customer: {case['message']}")
        verified_json = json.dumps(case["business"].as_dict(), ensure_ascii=False)
        print(f"  verified: {verified_json}")

        reply = claude_client.draft_response(
            customer_message=case["message"],
            facts=ExtractedFacts(destination_country="Colombia", language="en"),
            signals=case["signals"],
            business=case["business"],
            routing_decision=case["routing"],
            language="en",
        )
        latency = provider.calls[-1]["latency_s"] if provider.calls else 0.0
        print(f"\n  --- CLAUDE OUTPUT ({latency:.1f}s) ---")
        print("  " + (reply or "<None>").replace("\n", "\n  "))

        flagged = unsupported_numerics(reply or "", verified_json, case["message"])
        print(f"\n  unsupported numeric/temporal claims: {flagged if flagged else 'NONE'}")
        if flagged:
            failures += 1
            print("  >>> AUTOMATED FLAG - needs manual adjudication")
        print()

    print("=" * 78)
    print(f"cases run: {len(CASES)}   automated flags: {failures}")
    print("NOTE: automated flagging catches numeric/temporal invention only.")
    print("      Qualitative claims (policy, availability, status) need reading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
