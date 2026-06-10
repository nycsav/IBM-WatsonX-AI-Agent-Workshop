-- ============================================================================
-- E-commerce Iceberg Schema — Historical, analytical, and external
--
-- Principle: Iceberg holds what's NOT in Cassandra —
--   the cold archive of orders that have left the fulfillment pipeline,
--   pre-computed analytical rollups (daily/weekly/monthly),
--   time-series snapshots of metrics that Cassandra holds the current of,
--   and external data (competitor prices) not owned by our operational systems.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS iceberg_data.ecommerce;
USE iceberg_data.ecommerce;

-- ----------------------------------------------------------------------------
-- orders_archive — closed orders (delivered / returned / cancelled)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders_archive (
    order_id              VARCHAR,
    customer_id           VARCHAR,
    order_date            DATE,
    order_year            INTEGER,
    order_month           INTEGER,
    order_timestamp       TIMESTAMP,
    order_status          VARCHAR,
    payment_method        VARCHAR,
    payment_status        VARCHAR,
    subtotal              DECIMAL(12,2),
    tax_amount            DECIMAL(10,2),
    shipping_cost         DECIMAL(10,2),
    discount_amount       DECIMAL(10,2),
    total_amount          DECIMAL(12,2),
    currency              VARCHAR,
    shipping_city         VARCHAR,
    shipping_state        VARCHAR,
    shipping_country      VARCHAR,
    delivered_at          TIMESTAMP,
    returned_at           TIMESTAMP,
    item_count            INTEGER,
    created_at            TIMESTAMP
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['order_year', 'order_month']
);

-- ----------------------------------------------------------------------------
-- order_items_archive — line items for archived orders
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items_archive (
    order_id              VARCHAR,
    item_sequence         INTEGER,
    order_year            INTEGER,
    order_month           INTEGER,
    product_id            VARCHAR,
    product_sku           VARCHAR,
    product_name          VARCHAR,
    product_category      VARCHAR,
    quantity              INTEGER,
    unit_price            DECIMAL(12,2),
    discount_amount       DECIMAL(10,2),
    tax_amount            DECIMAL(10,2),
    line_total             DECIMAL(12,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['order_year', 'order_month']
);

-- ----------------------------------------------------------------------------
-- daily_sales_summary — one row per day × category × region (pre-rolled)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_sales_summary (
    summary_date          DATE,
    summary_year          INTEGER,
    summary_month         INTEGER,
    product_category      VARCHAR,
    shipping_country      VARCHAR,
    shipping_state        VARCHAR,
    order_count           BIGINT,
    unit_count            BIGINT,
    gross_revenue         DECIMAL(14,2),
    discount_total        DECIMAL(12,2),
    net_revenue           DECIMAL(14,2),
    return_count          BIGINT,
    return_amount         DECIMAL(12,2),
    unique_customers      BIGINT
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['summary_year', 'summary_month']
);

-- ----------------------------------------------------------------------------
-- customer_ltv_monthly — month-end snapshot of each customer's LTV
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customer_ltv_monthly (
    customer_id           VARCHAR,
    snapshot_year         INTEGER,
    snapshot_month        INTEGER,
    snapshot_date         DATE,
    ltv                   DECIMAL(14,2),
    cumulative_orders     INTEGER,
    orders_this_month     INTEGER,
    spend_this_month      DECIMAL(12,2),
    loyalty_tier          VARCHAR,
    is_active             BOOLEAN
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['snapshot_year', 'snapshot_month']
);

-- ----------------------------------------------------------------------------
-- product_performance_weekly — weekly rollup per product
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_performance_weekly (
    product_id            VARCHAR,
    product_category      VARCHAR,
    week_start_date       DATE,
    week_year             INTEGER,
    week_of_year          INTEGER,
    units_sold            INTEGER,
    gross_revenue         DECIMAL(12,2),
    average_selling_price DECIMAL(10,2),
    return_rate           DECIMAL(5,4),
    review_count          INTEGER,
    rating_average        DECIMAL(3,2),
    stock_start_of_week   INTEGER,
    stock_end_of_week     INTEGER,
    velocity_rank         INTEGER
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['week_year']
);

-- ----------------------------------------------------------------------------
-- cohort_retention — acquisition-cohort retention matrix
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cohort_retention (
    cohort_year           INTEGER,
    cohort_month          INTEGER,
    months_since_acquisition INTEGER,
    cohort_size           INTEGER,
    active_customers      INTEGER,
    retention_rate        DECIMAL(5,4),
    revenue_in_period     DECIMAL(14,2),
    avg_revenue_per_active DECIMAL(12,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['cohort_year']
);

-- ----------------------------------------------------------------------------
-- marketing_attribution — historical campaign → conversion data
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketing_attribution (
    conversion_id         VARCHAR,
    customer_id           VARCHAR,
    order_id              VARCHAR,
    conversion_timestamp  TIMESTAMP,
    conversion_year       INTEGER,
    conversion_month      INTEGER,
    campaign_id           VARCHAR,
    campaign_name         VARCHAR,
    channel               VARCHAR,
    touch_count           INTEGER,
    days_to_conversion    INTEGER,
    conversion_value      DECIMAL(12,2),
    attributed_revenue    DECIMAL(12,2)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['conversion_year', 'conversion_month']
);

-- ----------------------------------------------------------------------------
-- competitor_prices_weekly — external-flavored data (weekly crawl)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS competitor_prices_weekly (
    week_start_date       DATE,
    week_year             INTEGER,
    our_product_id        VARCHAR,
    our_sku               VARCHAR,
    competitor_name       VARCHAR,
    competitor_sku        VARCHAR,
    competitor_price      DECIMAL(10,2),
    currency              VARCHAR,
    in_stock              BOOLEAN,
    crawl_source          VARCHAR,
    crawl_timestamp       TIMESTAMP
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['week_year']
);
