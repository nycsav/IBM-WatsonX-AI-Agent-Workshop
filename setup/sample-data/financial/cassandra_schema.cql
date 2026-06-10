-- ============================================================================
-- Financial Cassandra Schema — Operational / hot-window only
--
-- Cassandra holds: in-flight transaction authorizations, current account
-- balances, pending transfers, open fraud cases, last-30d card activity,
-- and current card statuses. Everything archived / aggregated / external
-- (market data, statements, risk history) lives in Iceberg.
-- ============================================================================

CREATE KEYSPACE IF NOT EXISTS financial
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE financial;

-- ----------------------------------------------------------------------------
-- customers — core customer profile + current risk tier
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id           UUID PRIMARY KEY,
    email                 TEXT,
    first_name            TEXT,
    last_name             TEXT,
    phone                 TEXT,
    date_of_birth         DATE,
    ssn_last4             TEXT,
    created_at            TIMESTAMP,
    account_status        TEXT,          -- active | suspended | closed
    risk_tier             TEXT,          -- low | medium | high | restricted (CURRENT)
    kyc_verified          BOOLEAN,
    home_city             TEXT,
    home_state            TEXT,
    home_country          TEXT,
    updated_at            TIMESTAMP
);
CREATE INDEX IF NOT EXISTS financial_customers_email_idx ON customers (email);

-- ----------------------------------------------------------------------------
-- accounts — current accounts with live balances
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    account_id            UUID PRIMARY KEY,
    customer_id           UUID,
    account_type          TEXT,          -- checking | savings | credit | investment
    account_number_masked TEXT,
    opened_at             TIMESTAMP,
    status                TEXT,          -- active | frozen | closed
    current_balance       DECIMAL,       -- LIVE
    available_balance     DECIMAL,       -- LIVE (current - holds)
    credit_limit          DECIMAL,
    currency              TEXT,
    updated_at            TIMESTAMP
);
CREATE INDEX IF NOT EXISTS accounts_customer_idx ON accounts (customer_id);

-- ----------------------------------------------------------------------------
-- transactions_authorizing — payment requests being authorized RIGHT NOW
-- (hot, sub-second access path; TTL'd in real systems once terminal)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions_authorizing (
    account_id            UUID,
    transaction_id        TIMEUUID,
    initiated_at          TIMESTAMP,
    amount                DECIMAL,
    currency              TEXT,
    transaction_type      TEXT,          -- purchase | withdrawal | transfer | payment
    merchant_name         TEXT,
    merchant_category     TEXT,          -- mcc category name
    merchant_country      TEXT,
    channel               TEXT,          -- card | online | atm | mobile
    auth_status           TEXT,          -- requesting | approved | declined
    auth_code             TEXT,
    decline_reason        TEXT,
    PRIMARY KEY (account_id, transaction_id)
) WITH CLUSTERING ORDER BY (transaction_id DESC);

-- ----------------------------------------------------------------------------
-- card_transactions_recent — authorized card activity in last 30 days
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS card_transactions_recent (
    card_id               UUID,
    txn_date              DATE,
    transaction_id        UUID,
    account_id            UUID,
    customer_id           UUID,
    txn_timestamp         TIMESTAMP,
    amount                DECIMAL,
    currency              TEXT,
    merchant_name         TEXT,
    merchant_category     TEXT,
    merchant_country      TEXT,
    posted                BOOLEAN,
    PRIMARY KEY ((card_id), txn_date, transaction_id)
) WITH CLUSTERING ORDER BY (txn_date DESC, transaction_id DESC);

-- ----------------------------------------------------------------------------
-- card_status_current — active/blocked/frozen per card
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS card_status_current (
    card_id               UUID PRIMARY KEY,
    account_id            UUID,
    customer_id           UUID,
    card_number_last4     TEXT,
    card_type             TEXT,          -- debit | credit
    network               TEXT,          -- visa | mastercard | amex
    status                TEXT,          -- active | blocked | frozen | expired
    issued_at             TIMESTAMP,
    expires_on            DATE,
    status_updated_at     TIMESTAMP
);
CREATE INDEX IF NOT EXISTS cards_account_idx ON card_status_current (account_id);

-- ----------------------------------------------------------------------------
-- transfers_pending — wires/ACH in flight
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transfers_pending (
    source_account_id     UUID,
    transfer_id           UUID,
    initiated_at          TIMESTAMP,
    transfer_type         TEXT,          -- wire | ach | internal
    destination_account   TEXT,
    destination_bank      TEXT,
    amount                DECIMAL,
    currency              TEXT,
    status                TEXT,          -- pending | processing | flagged
    scheduled_settlement  DATE,
    PRIMARY KEY (source_account_id, transfer_id)
) WITH CLUSTERING ORDER BY (transfer_id DESC);

-- ----------------------------------------------------------------------------
-- fraud_alerts_open — active, unacknowledged fraud cases
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fraud_alerts_open (
    customer_id           UUID,
    alert_id              UUID,
    raised_at             TIMESTAMP,
    severity              TEXT,          -- low | medium | high | critical
    alert_type            TEXT,          -- velocity | geo_anomaly | amount_anomaly | card_not_present
    triggering_txn_id     UUID,
    risk_score            DECIMAL,
    status                TEXT,          -- open | investigating | escalated
    assigned_to           TEXT,
    PRIMARY KEY (customer_id, alert_id)
) WITH CLUSTERING ORDER BY (alert_id DESC);
