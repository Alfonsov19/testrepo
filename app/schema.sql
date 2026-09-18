-- Business reference data (source of truth for company facts).
CREATE TABLE IF NOT EXISTS countries (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    active  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS services (
    id                   INTEGER PRIMARY KEY,
    destination_country  TEXT NOT NULL,
    service_type         TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1,
    transit_time_text    TEXT,
    UNIQUE (destination_country, service_type)
);

CREATE TABLE IF NOT EXISTS rates (
    id              INTEGER PRIMARY KEY,
    service_id      INTEGER NOT NULL REFERENCES services(id),
    min_weight      REAL NOT NULL,
    max_weight      REAL NOT NULL,
    price           REAL NOT NULL,
    currency        TEXT NOT NULL,
    effective_from  TEXT NOT NULL,
    effective_to    TEXT
);

CREATE TABLE IF NOT EXISTS restrictions (
    id                   INTEGER PRIMARY KEY,
    destination_country  TEXT NOT NULL,
    category             TEXT NOT NULL,
    rule_text            TEXT NOT NULL,
    active               INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS business_info (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Interaction log (analytics source).
CREATE TABLE IF NOT EXISTS conversations (
    id                  INTEGER PRIMARY KEY,
    created_at          TEXT NOT NULL,
    customer_reference  TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id),
    direction        TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    text             TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inquiries (
    id                                   INTEGER PRIMARY KEY,
    message_id                           INTEGER NOT NULL REFERENCES messages(id),
    destination_country                  TEXT,
    language                             TEXT,
    sales_lead_probability               REAL,
    pricing_request_probability          REAL,
    tracking_request_probability         REAL,
    restriction_question_probability     REAL,
    complaint_probability                REAL,
    complex_shipment_probability         REAL,
    shipment_specific_issue_probability  REAL,
    routing_decision                     TEXT NOT NULL,
    routing_reason                       TEXT NOT NULL,
    generated_response                   TEXT,
    human_reviewed                       INTEGER NOT NULL DEFAULT 0,
    human_edited                         INTEGER NOT NULL DEFAULT 0,
    sent                                 INTEGER NOT NULL DEFAULT 0,
    jev_model                            TEXT,
    processing_ms                        INTEGER,
    created_at                           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inquiries_routing ON inquiries(routing_decision);
CREATE INDEX IF NOT EXISTS idx_inquiries_country ON inquiries(destination_country);
CREATE INDEX IF NOT EXISTS idx_inquiries_created ON inquiries(created_at);
