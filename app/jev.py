"""Jev client - seven independent Noul judgments over one customer message.

Design rules, each established by measurement during qualification:

* **One state field.** `state` carries exactly `customer_message` and nothing
  else. Neighbouring records measurably shift judgments about the target
  message, and prompt-level scoping ("ignore the other fields") made it worse,
  not better. Isolation is enforced here structurally.
* **One Noul per signal.** Independent propositions can all be true at once.
  A mutually-exclusive Choice forces them to compete and becomes sensitive to
  clause order.
* **Pinned model.** Never an alias - alias movement would silently change
  behaviour under a fixed threshold.
* **No retries.** A failed judgment routes to review rather than being retried
  into a different answer.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app import config
from app.models import Signals

logger = logging.getLogger(__name__)

ENDPOINT_PATH = "/v1/systemone"

# Wording is fixed: thresholds are only meaningful against the exact question
# they were measured on. Changing text here invalidates the qualification runs.
QUESTIONS: dict[str, str] = {
    "sales_lead": (
        "Does `customer_message` indicate a prospective customer interested in "
        "purchasing or using a service?"
    ),
    "pricing_request": (
        "Is the customer asking about a price, rate, cost, quote, or how much a "
        "service would cost?"
    ),
    "tracking_request": (
        "Is the customer asking about the current location, status, tracking, "
        "delivery progress, or arrival of an existing shipment?"
    ),
    "restriction_question": (
        "Is the customer asking whether an item can be shipped or about shipping "
        "restrictions, prohibited items, quantity limits, customs restrictions, "
        "or permitted contents?"
    ),
    "complaint": (
        "Is the customer expressing dissatisfaction or complaining about a service, "
        "shipment, delay, charge, employee interaction, damage, loss, or other problem?"
    ),
    "complex_shipment": (
        "Does `customer_message` describe a shipment that is clearly non-standard or "
        "operationally complex, such as household contents, freight, pallets, "
        "commercial quantities, very large quantities, multiple containers, "
        "unusually heavy cargo, oversized items, or a move involving many belongings?"
    ),
    "shipment_specific_issue": (
        "Does answering this request require information about a specific existing "
        "shipment, tracking number, transaction, customer account, claim, customs "
        "case, or other customer-specific record?"
    ),
}


def build_request(customer_message: str) -> dict:
    """Build the request body. State isolation is asserted, not hoped for."""
    body = {
        "state": {"customer_message": customer_message},
        "model": config.SETTINGS.jev_model,
        "questions": {
            name: {"type": "noul", "instructions": text}
            for name, text in QUESTIONS.items()
        },
    }
    assert list(body["state"]) == ["customer_message"], "state isolation violated"
    assert not body["model"].endswith("latest"), "model must be pinned, not an alias"
    return body


def get_signals(customer_message: str, timeout: float = 30.0) -> Signals:
    """Call Jev once. On any failure return unavailable signals - never retry.

    Unavailable signals route to human review via `routing.decide()`, which is
    the safe direction: a missing judgment must not become an automatic reply.
    """
    if not config.SETTINGS.jev_available:
        logger.warning("TYPESAFE_API_KEY not set - Jev signals unavailable")
        return Signals(available=False)

    body = json.dumps(build_request(customer_message)).encode()
    request = urllib.request.Request(
        config.SETTINGS.typesafe_base_url.rstrip("/") + ENDPOINT_PATH,
        data=body,
        headers={
            "Authorization": f"Bearer {config.SETTINGS.typesafe_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        logger.error("Jev HTTP %s", exc.code)  # body may echo the request; keep it out of logs
        return Signals(available=False)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.error("Jev call failed: %s", type(exc).__name__)
        return Signals(available=False)

    try:
        answers = payload["answers"]
        values = {name: float(answers[name]["noul"]) for name in QUESTIONS}
    except (KeyError, TypeError, ValueError) as exc:
        logger.error("Jev response malformed: %s", type(exc).__name__)
        return Signals(available=False)

    return Signals(**values, model=payload.get("model"), available=True)
