"""FastAPI application - the one pipeline and the human-review endpoints.

    message -> Jev signals -> fact extraction -> database lookup
            -> deterministic routing -> Claude draft -> persisted inquiry
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import business, claude_client, jev, logging_store, routing
from app import config
from app.db import bootstrap, connect

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap()
    if not config.SETTINGS.jev_available:
        logger.warning("TYPESAFE_API_KEY not set - every inquiry will route REVIEW")
    if not config.SETTINGS.claude_available:
        logger.warning("ANTHROPIC_API_KEY not set - no extraction, no drafts")
    yield


app = FastAPI(
    title="Client Relationship Chatbot (prototype)", version="0.1.0", lifespan=lifespan
)


class MessageIn(BaseModel):
    customer_message: str = Field(min_length=1, max_length=8000)
    customer_reference: str | None = None
    conversation_id: int | None = None


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "jev_model": config.SETTINGS.jev_model,
        "claude_model": config.SETTINGS.claude_model,
        "jev_configured": config.SETTINGS.jev_available,
        "claude_configured": config.SETTINGS.claude_available,
        "signal_threshold": config.SETTINGS.signal_threshold,
    }


@app.post("/messages")
def handle_message(payload: MessageIn) -> dict:
    """Run one customer message through the full pipeline."""
    started = time.monotonic()
    text = payload.customer_message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="customer_message is empty")

    # 1. Semantic signals. One message, one request, seven independent judgments.
    signals = jev.get_signals(text)
    flags = signals.booleans(config.SETTINGS.signal_threshold)

    # 2. Facts needed for lookup. Missing is acceptable; invented is not.
    facts = claude_client.extract_facts(text)

    # 3. Verified company facts - only what this inquiry needs.
    verified = business.lookup(
        facts,
        needs_pricing=flags["pricing_request"],
        needs_restrictions=flags["restriction_question"],
    )

    # 4. Deterministic routing. Jev does not decide this.
    decision = routing.decide(signals, facts, verified)

    # 5. Draft from verified facts only.
    draft = claude_client.draft_response(
        customer_message=text,
        facts=facts,
        signals=signals,
        business=verified,
        routing_decision=decision.decision,
        language=facts.language,
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # 6. Persist.
    with connect() as conn:
        conversation_id = payload.conversation_id or logging_store.create_conversation(
            conn, payload.customer_reference
        )
        message_id = logging_store.add_message(conn, conversation_id, "inbound", text)
        inquiry_id = logging_store.record_inquiry(
            conn, message_id, signals, facts, verified, decision, draft, elapsed_ms
        )
        conn.commit()

    logger.info(
        "inquiry %s routed %s (%s) in %sms",
        inquiry_id, decision.decision, decision.reason_text, elapsed_ms,
    )
    return {
        "conversation_id": conversation_id,
        "inquiry_id": inquiry_id,
        "extracted_facts": facts.as_dict(),
        "jev_signals": {
            "probabilities": {k: v for k, v in signals.as_dict().items()
                              if isinstance(v, float)},
            "booleans": flags,
            "model": signals.model,
            "available": signals.available,
        },
        "routing_decision": decision.decision,
        "routing_reason": decision.reason_text,
        "verified_business_data": verified.as_dict(),
        "suggested_response": draft,
        "processing_ms": elapsed_ms,
    }


@app.get("/review")
def list_review() -> dict:
    items = logging_store.pending_review()
    return {"count": len(items), "inquiries": items}


class EditIn(BaseModel):
    text: str = Field(min_length=1)


@app.post("/review/{inquiry_id}/approve")
def approve(inquiry_id: int) -> dict:
    if not logging_store.approve(inquiry_id):
        raise HTTPException(status_code=404, detail="inquiry not found")
    return {"inquiry_id": inquiry_id, "human_reviewed": True, "sent": True}


@app.post("/review/{inquiry_id}/edit")
def edit(inquiry_id: int, payload: EditIn) -> dict:
    if not logging_store.save_edit(inquiry_id, payload.text):
        raise HTTPException(status_code=404, detail="inquiry not found")
    return {"inquiry_id": inquiry_id, "human_reviewed": True, "human_edited": True}
