-- Migration: create historical_clearing_adjustment table
-- Run once against the production DB (idempotent via IF NOT EXISTS)

CREATE TABLE IF NOT EXISTS historical_clearing_adjustment (
    id                      SERIAL PRIMARY KEY,
    safe_box_id             INTEGER NOT NULL REFERENCES safe_box(id),
    amount                  DOUBLE PRECISION NOT NULL,
    adjustment_type         VARCHAR(50) NOT NULL,
    reference_voucher_id    INTEGER REFERENCES voucher(id),
    reference_voucher_number VARCHAR(50),
    reason                  TEXT NOT NULL,
    created_by              VARCHAR(100) NOT NULL,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    approved_by             VARCHAR(100),
    approved_at             TIMESTAMP,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending',
    safe_box_transaction_id INTEGER REFERENCES safe_box_transaction(id),
    journal_entry_id        INTEGER REFERENCES journal_entry(id)
);

CREATE INDEX IF NOT EXISTS ix_hca_safe_box_id ON historical_clearing_adjustment(safe_box_id);
CREATE INDEX IF NOT EXISTS ix_hca_status      ON historical_clearing_adjustment(status);
