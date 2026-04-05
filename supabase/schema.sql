-- ============================================================
-- SMS Spend Agent — Supabase Schema
-- Run this entire file once in Supabase → SQL Editor
-- ============================================================

-- SMS messages (raw, exactly as received from the phone)
CREATE TABLE IF NOT EXISTS sms_messages (
    id           TEXT        PRIMARY KEY,          -- deterministic hash or device-assigned ID
    sender       TEXT        NOT NULL,             -- e.g. "HDFCBK", "+919876543210"
    body         TEXT        NOT NULL,
    timestamp    TIMESTAMPTZ NOT NULL,             -- exact time SMS was received (full precision)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sms_timestamp ON sms_messages (timestamp DESC);

-- Parsed financial transactions extracted from SMS
CREATE TABLE IF NOT EXISTS transactions (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    sms_id           TEXT        NOT NULL REFERENCES sms_messages (id) ON DELETE CASCADE,
    amount           NUMERIC(14,2) NOT NULL,
    transaction_type TEXT        NOT NULL CHECK (transaction_type IN ('debit','credit','unknown')),
    timestamp        TIMESTAMPTZ NOT NULL,         -- same as the parent SMS timestamp
    merchant         TEXT,
    account_last4    CHAR(4),
    payment_mode     TEXT,                         -- UPI, NEFT, IMPS, ATM, Credit Card, etc.
    reference        TEXT,
    bank             TEXT,
    raw_sms          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sms_id)                                -- one transaction per SMS
);

CREATE INDEX IF NOT EXISTS idx_txn_timestamp      ON transactions (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_txn_type           ON transactions (transaction_type);
CREATE INDEX IF NOT EXISTS idx_txn_merchant       ON transactions (merchant);
CREATE INDEX IF NOT EXISTS idx_txn_bank           ON transactions (bank);
CREATE INDEX IF NOT EXISTS idx_txn_payment_mode   ON transactions (payment_mode);

-- ============================================================
-- Helper function: returns the current Postgres DB size in bytes.
-- Called by the Python app to monitor free-tier usage (500 MB cap).
-- ============================================================
CREATE OR REPLACE FUNCTION get_db_size_bytes()
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER   -- runs as the DB owner so it can see system catalogs
STABLE
AS $$
    SELECT pg_database_size(current_database());
$$;
