"""Claude client - fact extraction and response drafting.

Claude phrases; it never supplies facts. Rates, restrictions, schedules,
tracking status, policies and service availability come from the business
database and are passed in as verified data. When a needed fact is missing the
draft says the inquiry needs review rather than inventing one.
"""
from __future__ import annotations

import json
import logging

import anthropic
from pydantic import BaseModel, Field

from app import config
from app.models import BusinessData, ExtractedFacts, Signals

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.SETTINGS.anthropic_api_key)
    return _client


class _FactSchema(BaseModel):
    """Extraction target. Every field is optional - missing is fine, invented is not."""

    origin_country_or_city: str | None = Field(default=None)
    destination_country: str | None = Field(default=None)
    weight: float | None = Field(default=None)
    weight_unit: str | None = Field(default=None)
    service_type: str | None = Field(default=None)
    language: str | None = Field(default=None)
    items_mentioned: list[str] = Field(default_factory=list)


_EXTRACTION_SYSTEM = (
    "Extract only what the message literally states. If a field is not stated, "
    "return null for it - never guess, infer, or fill in a plausible value. "
    "Use the English country name. `language` is the ISO 639-1 code of the "
    "message itself (en, es, fr, ...). `items_mentioned` lists goods the "
    "customer says they want to ship."
)


def extract_facts(customer_message: str) -> ExtractedFacts:
    """Pull the few fields needed for database lookup. Missing values are expected."""
    if not config.SETTINGS.claude_available:
        logger.warning("ANTHROPIC_API_KEY not set - fact extraction unavailable")
        return ExtractedFacts(available=False, note="ANTHROPIC_API_KEY not configured")

    try:
        response = _get_client().messages.parse(
            model=config.SETTINGS.claude_model,
            max_tokens=2048,
            system=_EXTRACTION_SYSTEM,
            messages=[{"role": "user", "content": customer_message}],
            output_format=_FactSchema,
        )
        parsed = response.parsed_output
    except anthropic.APIStatusError as exc:
        logger.error("extraction failed: HTTP %s", exc.status_code)
        return ExtractedFacts(available=False, note="extraction API error")
    except anthropic.APIConnectionError:
        logger.error("extraction failed: connection error")
        return ExtractedFacts(available=False, note="extraction connection error")

    if parsed is None:
        return ExtractedFacts(available=False, note="extraction returned no data")

    return ExtractedFacts(
        origin_country_or_city=parsed.origin_country_or_city,
        destination_country=parsed.destination_country,
        weight=parsed.weight,
        weight_unit=parsed.weight_unit,
        service_type=parsed.service_type,
        language=parsed.language,
        items_mentioned=list(parsed.items_mentioned),
        available=True,
    )


_DRAFT_SYSTEM = (
    "You draft replies for a shipping company's support team. A human reviews "
    "every draft before it reaches a customer.\n\n"
    "The VERIFIED BUSINESS DATA block is authoritative and is the ONLY source of "
    "company facts. You may organise and phrase it. You may NOT invent or alter "
    "rates, prices, restrictions, schedules, transit times, tracking status, "
    "policies, or whether a service exists. If the data needed to answer is "
    "absent, say the inquiry is being passed to a colleague for review - do not "
    "guess and do not promise a specific outcome.\n\n"
    "Reply in the customer's language. Be brief and plain. Do not invent a "
    "signature, ticket number, or timeframe."
)


def draft_response(
    customer_message: str,
    facts: ExtractedFacts,
    signals: Signals,
    business: BusinessData,
    routing_decision: str,
    language: str | None,
) -> str | None:
    """Draft a reply from verified facts. Returns None if Claude is unavailable."""
    if not config.SETTINGS.claude_available:
        logger.warning("ANTHROPIC_API_KEY not set - no draft generated")
        return None

    prompt = (
        f"CUSTOMER MESSAGE:\n{customer_message}\n\n"
        f"EXTRACTED FACTS (may be incomplete):\n"
        f"{json.dumps(facts.as_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"SIGNAL FLAGS (for tone only, not facts):\n"
        f"{json.dumps(signals.booleans(config.SETTINGS.signal_threshold), indent=2)}\n\n"
        f"VERIFIED BUSINESS DATA (authoritative; empty means we do not have it):\n"
        f"{json.dumps(business.as_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"ROUTING: {routing_decision}\n"
        f"REPLY LANGUAGE: {language or 'match the customer message'}\n\n"
        "Write the draft reply only."
    )
    try:
        response = _get_client().messages.create(
            model=config.SETTINGS.claude_model,
            max_tokens=1024,
            system=_DRAFT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        logger.error("draft failed: HTTP %s", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        logger.error("draft failed: connection error")
        return None

    return "".join(b.text for b in response.content if b.type == "text").strip() or None
