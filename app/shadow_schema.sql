-- Shadow-mode pilot overlay.
-- One row per shadow-processed inquiry, holding the pilot-only fields that the
-- production `inquiries` table does not carry. Production tables are unchanged.
CREATE TABLE IF NOT EXISTS shadow_records (
    id                             INTEGER PRIMARY KEY,
    inquiry_id                     INTEGER NOT NULL REFERENCES inquiries(id),
    source_ref                     TEXT,      -- caller's own id for the inquiry
    extracted_facts                TEXT,      -- JSON
    verified_business_data_used    TEXT,      -- JSON
    -- automated safety flags (computed at processing time)
    unsupported_fact_detected      INTEGER NOT NULL DEFAULT 0,
    unsupported_fact_detail        TEXT,      -- JSON list of categories + tokens
    missing_fact_detected          INTEGER NOT NULL DEFAULT 0,
    missing_fact_detail            TEXT,
    contradiction_detected         INTEGER NOT NULL DEFAULT 0,
    contradiction_detail           TEXT,
    -- human evaluation (filled in AFTER processing, by a person, never by code)
    actual_human_response          TEXT,
    human_would_approve_without_edit INTEGER,   -- NULL until a human rates it
    human_edit_required            INTEGER,
    edit_reason                    TEXT,
    correct_business_facts         INTEGER,
    complete_enough                INTEGER,
    correct_language               INTEGER,
    appropriate_tone               INTEGER,
    evaluated_at                   TEXT,
    evaluator                      TEXT,
    created_at                     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shadow_inquiry ON shadow_records(inquiry_id);
CREATE INDEX IF NOT EXISTS idx_shadow_flags
    ON shadow_records(unsupported_fact_detected, contradiction_detected);
