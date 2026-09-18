# Client Relationship Chatbot — Version 1 prototype

Backend prototype. One customer message goes in; semantic signals, verified
business facts, a deterministic routing decision and a draft reply come out,
and the whole interaction is logged as structured data.

```
message ─► Jev signals ─► fact extraction ─► database lookup
        ─► deterministic routing ─► Claude draft ─► persisted inquiry
```

## Architecture in one paragraph

**Jev** answers seven narrow yes/no questions about the message and nothing
else. **Application code** decides AUTO vs REVIEW — Jev is never asked to make
that call. The **SQLite database** is the source of truth for rates, services,
restrictions and schedules. **Claude** extracts a few lookup fields and phrases
a draft from facts the application verified; it is told explicitly that the
verified data is authoritative and that it may not invent rates, restrictions,
schedules, tracking status, policies or service availability. **Humans** review
everything that routes REVIEW.

## Run it

```bash
cd /home/user/testrepo
pip install -r requirements.txt

cp .env.example .env          # then fill in the two keys
set -a; source .env; set +a   # export them into the shell

python -m app.db              # create ./crm.db and load TEST seed data
python -m pytest tests/ -q    # 35 tests, no network calls
uvicorn app.main:app --reload --port 8000
```

Send a message:

```bash
curl -s -X POST localhost:8000/messages \
  -H 'Content-Type: application/json' \
  -d '{"customer_message":"How much is it to send a 40 lb box to Colombia?"}' | python -m json.tool
```

Review queue:

```bash
curl -s localhost:8000/review | python -m json.tool
curl -s -X POST localhost:8000/review/1/edit -H 'Content-Type: application/json' \
     -d '{"text":"Edited reply."}'
curl -s -X POST localhost:8000/review/1/approve
```

Interactive docs: <http://localhost:8000/docs>

## Configuration

| Variable | Required | Default | Effect if missing |
|---|---|---|---|
| `TYPESAFE_API_KEY` | yes | — | No signals; **every** inquiry routes REVIEW |
| `ANTHROPIC_API_KEY` | yes | — | No extraction and no draft; inquiries route REVIEW |
| `JEV_MODEL` | no | `jev-1.13.0` | Pinned on purpose — never use an alias |
| `CLAUDE_MODEL` | no | `claude-opus-5` | |
| `CRM_DB_PATH` | no | `./crm.db` | |
| `SIGNAL_THRESHOLD` | no | `0.50` | Provisional; see below |

Missing credentials degrade toward human review. The app never fabricates a
fact to fill a gap.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Config and which integrations are wired up |
| `POST` | `/messages` | Run one message through the pipeline |
| `GET` | `/review` | Inquiries awaiting a human |
| `POST` | `/review/{id}/approve` | Mark a draft approved and sent |
| `POST` | `/review/{id}/edit` | Save a human-edited reply |

## Routing rule

All of it lives in `app/routing.py` as one function. REVIEW if **any** holds:

1. `complaint`, `complex_shipment` or `shipment_specific_issue` ≥ threshold
2. Jev signals or fact extraction unavailable
3. `pricing_request` ≥ threshold but no matching standard rate in the database
4. `restriction_question` ≥ threshold but no restriction records for the country

Otherwise AUTO. Every reason is recorded, not just the first.

## Why the design looks like this

Each rule below came out of a measurement, not a preference:

- **One state field per Jev request.** Neighbouring records measurably shift
  judgments about the target message. Telling the model to "ignore the other
  fields" made it *worse*. Isolation is enforced structurally in
  `jev.build_request()` with an assertion.
- **One Noul per signal, never a mutually-exclusive Choice.** Independent
  propositions can all be true at once; forcing them to compete made the answer
  depend on clause order.
- **Pinned model, never an alias.** Alias movement would silently change
  behaviour under a fixed threshold.
- **No retries on a failed judgment.** A retry can return a different answer;
  a failure routes to a human instead.
- **`complex_shipment`, not "is a custom quote required".** The latter asks the
  model a question only your rate card can answer and produced a 33%-precision
  signal. Asking only about observable message content produced a clean one.

## Threshold caveat

`0.50` is **provisional**, carried over from synthetic qualification. It has not
been validated against real traffic. Both the raw probability and the derived
boolean are stored for every signal, so thresholds can be re-tuned later from
logged data without re-running anything.

## Test data warning

Everything in `app/seed.sql` is invented placeholder data, marked `TEST DATA`
in every row. **The rates are not real company rates.** Replace the seed data
before any real use.

## Analytics

Answerable with plain SQL over `inquiries`:

```sql
-- AUTO vs REVIEW split
SELECT routing_decision, COUNT(*) FROM inquiries GROUP BY routing_decision;

-- inquiries by country
SELECT destination_country, COUNT(*) FROM inquiries GROUP BY destination_country;

-- signal mix (pricing / tracking / complaints / leads / complex)
SELECT SUM(pricing_request_probability  >= 0.5) AS pricing,
       SUM(tracking_request_probability >= 0.5) AS tracking,
       SUM(complaint_probability        >= 0.5) AS complaints,
       SUM(sales_lead_probability       >= 0.5) AS leads,
       SUM(complex_shipment_probability >= 0.5) AS complex_leads
FROM inquiries;

-- human edit rate and average processing time
SELECT AVG(human_edited) AS edit_rate, AVG(processing_ms) AS avg_ms FROM inquiries;
```

## Moving to PostgreSQL

All SQL is confined to `app/db.py`, `app/business.py` and
`app/logging_store.py`, uses parameter binding, and avoids SQLite-specific
syntax. Swapping the driver means changing `connect()` and the placeholder
style — the chatbot logic does not change.

## Not built yet (deliberately)

No WhatsApp/email/web chat, no auth, no deployment, no frontend, no Power BI
connector, no agents, no RAG, no vector database, no queue.

## Layout

```
app/
  config.py         settings from the environment
  models.py         dataclasses (Signals, ExtractedFacts, BusinessData, RoutingDecision)
  db.py             connection + schema/seed bootstrap
  schema.sql        DDL
  seed.sql          TEST DATA ONLY
  jev.py            seven Nouls, one state field, pinned model, no retries
  claude_client.py  fact extraction + draft generation
  business.py       validation, unit conversion, verified lookups
  routing.py        the routing rule, pure and testable
  logging_store.py  conversations / messages / inquiries
  main.py           FastAPI app
tests/
  test_routing.py   the routing rule (no network)
  test_business.py  lookup, validation, unit conversion
  test_jev_request.py  request shape and state isolation
  test_pipeline.py  end-to-end through HTTP with Jev/Claude stubbed
```
