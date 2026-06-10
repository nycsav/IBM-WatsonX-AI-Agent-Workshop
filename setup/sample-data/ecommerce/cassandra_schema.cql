-- ============================================================================
-- E-commerce Cassandra Schema — Operational / hot-window only
--
-- Principle: Cassandra holds data accessed per-key at low latency:
--   current state (customer tier, live inventory),
--   the hot time-window (carts, in-flight orders, last-24h sessions,
--   last-30d inventory moves & reviews).
-- Older / aggregated / external data lives in Iceberg. The two stores are
-- complementary, not copies of each other.
-- ============================================================================

CREATE KEYSPACE IF NOT EXISTS ecommerce
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE ecommerce;

-- ----------------------------------------------------------------------------
-- customers — live profile + derived current-state metrics
-- Cassandra is the system of record for "what is this customer right now".
-- Historical snapshots of the same metrics (LTV over time) live in Iceberg.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    customer_id           UUID PRIMARY KEY,
    email                 TEXT,
    first_name            TEXT,
    last_name             TEXT,
    phone                 TEXT,
    created_at            TIMESTAMP,
    last_login            TIMESTAMP,
    account_status        TEXT,
    loyalty_tier          TEXT,
    current_ltv           DECIMAL,
    total_orders          INT,
    shipping_city         TEXT,
    shipping_state        TEXT,
    shipping_country      TEXT,
    marketing_opt_in      BOOLEAN,
    updated_at            TIMESTAMP
);
CREATE INDEX IF NOT EXISTS customers_email_idx ON customers (email);

-- ----------------------------------------------------------------------------
-- products — catalog with live stock counts
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    product_id            UUID PRIMARY KEY,
    sku                   TEXT,
    name                  TEXT,
    category              TEXT,
    subcategory           TEXT,
    brand                 TEXT,
    price                 DECIMAL,
    cost                  DECIMAL,
    currency              TEXT,
    stock_quantity        INT,
    reorder_level         INT,
    is_active             BOOLEAN,
    created_at            TIMESTAMP,
    updated_at            TIMESTAMP,
    rating_avg            DECIMAL,
    rating_count          INT
);
CREATE INDEX IF NOT EXISTS products_category_idx ON products (category);
CREATE INDEX IF NOT EXISTS products_sku_idx ON products (sku);

-- ----------------------------------------------------------------------------
-- active_carts — carts currently being filled
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS active_carts (
    customer_id           UUID,
    product_id            UUID,
    added_at              TIMESTAMP,
    quantity              INT,
    unit_price            DECIMAL,
    PRIMARY KEY (customer_id, product_id)
);

-- ----------------------------------------------------------------------------
-- orders_inflight — orders placed in the last 30 days that are NOT terminal
-- (pending | processing | shipped). Delivered/returned/cancelled move to
-- iceberg_data.ecommerce.orders_archive.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders_inflight (
    customer_id           UUID,
    order_date            DATE,
    order_id              UUID,
    order_timestamp       TIMESTAMP,
    order_status          TEXT,
    payment_method        TEXT,
    payment_status        TEXT,
    subtotal              DECIMAL,
    tax_amount            DECIMAL,
    shipping_cost         DECIMAL,
    discount_amount       DECIMAL,
    total_amount          DECIMAL,
    currency              TEXT,
    shipping_city         TEXT,
    shipping_state        TEXT,
    shipping_country      TEXT,
    tracking_number       TEXT,
    estimated_delivery_date DATE,
    created_at            TIMESTAMP,
    updated_at            TIMESTAMP,
    PRIMARY KEY ((customer_id), order_date, order_id)
) WITH CLUSTERING ORDER BY (order_date DESC, order_id DESC);

-- ----------------------------------------------------------------------------
-- order_items_inflight — line items for in-flight orders
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items_inflight (
    order_id              UUID,
    item_sequence         INT,
    product_id            UUID,
    product_name          TEXT,
    product_sku           TEXT,
    quantity              INT,
    unit_price            DECIMAL,
    discount_amount       DECIMAL,
    tax_amount            DECIMAL,
    line_total            DECIMAL,
    currency              TEXT,
    PRIMARY KEY (order_id, item_sequence)
) WITH CLUSTERING ORDER BY (item_sequence ASC);

-- ----------------------------------------------------------------------------
-- live_sessions — customer browsing sessions in the last 24 hours
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS live_sessions (
    customer_id           UUID,
    session_id            UUID,
    session_start         TIMESTAMP,
    session_end           TIMESTAMP,
    page_views            INT,
    cart_additions        INT,
    products_viewed_count INT,
    device_type           TEXT,
    browser               TEXT,
    referrer              TEXT,
    PRIMARY KEY (customer_id, session_id)
) WITH CLUSTERING ORDER BY (session_id DESC);

-- ----------------------------------------------------------------------------
-- inventory_ledger_recent — last 30 days of inventory movements
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory_ledger_recent (
    product_id            UUID,
    transaction_date      DATE,
    transaction_id        TIMEUUID,
    transaction_type      TEXT,
    quantity_change       INT,
    quantity_after        INT,
    reference_order_id    UUID,
    created_at            TIMESTAMP,
    PRIMARY KEY ((product_id, transaction_date), transaction_id)
) WITH CLUSTERING ORDER BY (transaction_id DESC);

-- ----------------------------------------------------------------------------
-- reviews_recent — product reviews submitted in the last 30 days
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews_recent (
    product_id            UUID,
    review_date           DATE,
    review_id             UUID,
    customer_id           UUID,
    rating                INT,
    title                 TEXT,
    review_text           TEXT,
    verified_purchase     BOOLEAN,
    created_at            TIMESTAMP,
    PRIMARY KEY ((product_id, review_date), review_id)
) WITH CLUSTERING ORDER BY (review_id DESC);
