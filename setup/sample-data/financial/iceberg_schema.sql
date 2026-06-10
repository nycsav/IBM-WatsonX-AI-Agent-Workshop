-- ============================================================================
-- Financial Iceberg Schema — Historical, analytical, external
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS iceberg_data.financial;
USE iceberg_data.financial;

-- ----------------------------------------------------------------------------
-- transactions_archive — authorized transactions older than 30 days
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions_archive (
    transaction_id        VARCHAR,
    account_id            VARCHAR,
    customer_id           VARCHAR,
    txn_date              DATE,
    txn_year              INTEGER,
    txn_month             INTEGER,
    txn_timestamp         TIMESTAMP,
    transaction_type      VARCHAR,
    amount                DECIMAL(14,2),
    currency              VARCHAR,
    merchant_name         VARCHAR,
    merchant_category     VARCHAR,
    merchant_country      VARCHAR,
    channel               VARCHAR,
    status                VARCHAR,       -- posted | reversed | disputed
    posted_at             TIMESTAMP
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['txn_year', 'txn_month']
);

-- ----------------------------------------------------------------------------
-- account_statements_monthly — closed monthly statements per account
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_statements_monthly (
    statement_id          VARCHAR,
    account_id            VARCHAR,
    customer_id           VARCHAR,
    statement_year        INTEGER,
    statement_month       INTEGER,
    period_start          DATE,
    period_end            DATE,
    opening_balance       DECIMAL(14,2),
    closing_balance       DECIMAL(14,2),
    total_credits         DECIMAL(14,2),
    total_debits          DECIMAL(14,2),
    transaction_count     INTEGER,
    fees_charged          DECIMAL(10,2),
    interest_earned       DECIMAL(10,2),
    minimum_balance       DECIMAL(14,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['statement_year', 'statement_month']
);

-- ----------------------------------------------------------------------------
-- fraud_training_labels — confirmed-fraud training set for ML models
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fraud_training_labels (
    label_id              VARCHAR,
    transaction_id        VARCHAR,
    customer_id           VARCHAR,
    labeled_at            TIMESTAMP,
    label_year            INTEGER,
    is_fraud              BOOLEAN,
    fraud_type            VARCHAR,       -- card_not_present | account_takeover | synthetic_id | merchant_collusion
    confidence            DECIMAL(4,3),
    loss_amount           DECIMAL(12,2),
    recovered_amount      DECIMAL(12,2),
    labeled_by            VARCHAR,       -- analyst | rule_engine | customer_dispute
    investigation_days    INTEGER
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['label_year']
);

-- ----------------------------------------------------------------------------
-- risk_assessment_history — quarterly snapshots of customer risk scores
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_assessment_history (
    customer_id           VARCHAR,
    snapshot_year         INTEGER,
    snapshot_quarter      INTEGER,
    snapshot_date         DATE,
    risk_score            DECIMAL(5,2),  -- 0..100
    risk_tier             VARCHAR,
    model_version         VARCHAR,
    pd_12mo               DECIMAL(5,4),  -- probability of default, 12 months
    loss_given_default    DECIMAL(5,4),
    exposure_at_default   DECIMAL(14,2),
    credit_limit          DECIMAL(14,2),
    utilization_pct       DECIMAL(5,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['snapshot_year']
);

-- ----------------------------------------------------------------------------
-- portfolio_metrics_daily — daily investment-portfolio rollup per customer
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_metrics_daily (
    customer_id           VARCHAR,
    account_id            VARCHAR,
    metric_date           DATE,
    metric_year           INTEGER,
    metric_month          INTEGER,
    portfolio_value       DECIMAL(14,2),
    daily_pnl             DECIMAL(12,2),
    daily_return_pct      DECIMAL(8,5),
    cumulative_return_pct DECIMAL(8,5),
    volatility_30d        DECIMAL(8,5),
    sharpe_ratio          DECIMAL(6,3),
    asset_class_mix       VARCHAR        -- e.g. '60/30/10' (stocks/bonds/cash)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['metric_year', 'metric_month']
);

-- ----------------------------------------------------------------------------
-- regulatory_filings — historical SAR/CTR/compliance events
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regulatory_filings (
    filing_id             VARCHAR,
    customer_id           VARCHAR,
    filed_at              TIMESTAMP,
    filing_year           INTEGER,
    filing_month          INTEGER,
    filing_type           VARCHAR,       -- SAR | CTR | OFAC | 314a | FBAR
    regulator             VARCHAR,
    amount_reported       DECIMAL(14,2),
    status                VARCHAR,       -- filed | acknowledged | amended | closed
    trigger_reason        VARCHAR
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['filing_year', 'filing_month']
);

-- ----------------------------------------------------------------------------
-- market_data_daily — external OHLCV feed for reference tickers
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data_daily (
    ticker                VARCHAR,
    asset_class           VARCHAR,       -- equity | bond | fx | commodity | crypto
    quote_date            DATE,
    quote_year            INTEGER,
    open_price            DECIMAL(14,4),
    high_price            DECIMAL(14,4),
    low_price             DECIMAL(14,4),
    close_price           DECIMAL(14,4),
    volume                BIGINT,
    currency              VARCHAR,
    source                VARCHAR        -- external feed vendor name
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['quote_year']
);
