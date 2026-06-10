# Workshop schemas — orientation

This is the only artifact the workshop hands you up front. Everything else — requirements, design, OpenAPI, code — your LLM produces from this.

**Pick one domain.** Feed your LLM this file plus your domain's two DDL files (`cassandra_schema.cql` and `iceberg_schema.sql`). Don't feed it all three domains — it'll get confused.

---

## How the data is organized

The workshop installs two stores. They are **complementary, not copies of each other.**

- **Cassandra** holds the hot, operational data: current state (customer profile, account balance, device status), the open work (in-flight orders, authorizing transactions, last-24h sensor readings), and anything you'd want to look up by key in milliseconds.
- **Iceberg** (queried via Presto, on watsonx.data) holds the cold archive (closed orders, posted transactions, sensor readings older than 24h), pre-computed analytical rollups (daily/weekly/monthly summaries), and external data feeds (competitor prices, market data, weather).

Your app will read from both. The federated query — joining a hot Cassandra read to a cold Iceberg read — is the point of the workshop.

The data is already loaded. You read from it; you don't load it.

---

## E-commerce — `setup/sample-data/ecommerce/`

DDL files: [`cassandra_schema.cql`](setup/sample-data/ecommerce/cassandra_schema.cql) · [`iceberg_schema.sql`](setup/sample-data/ecommerce/iceberg_schema.sql)

### Cassandra (`ecommerce` keyspace) — hot

| Table | What it holds |
|---|---|
| `customers` | live customer profile + current LTV / loyalty tier / total orders |
| `products` | product catalog with live stock counts |
| `active_carts` | carts currently being filled |
| `orders_inflight` | orders placed in last 30 days, not yet terminal (pending/processing/shipped) |
| `order_items_inflight` | line items for those in-flight orders |
| `live_sessions` | customer browsing sessions in the last 24 hours |
| `inventory_ledger_recent` | last 30 days of stock moves |
| `reviews_recent` | product reviews submitted in the last 30 days |

### Iceberg (`iceberg_data.ecommerce`) — cold + analytical + external

| Table | What it holds |
|---|---|
| `orders_archive` | closed orders (delivered / returned / cancelled), partitioned by `order_year`, `order_month` |
| `order_items_archive` | line items for archived orders |
| `daily_sales_summary` | one row per day × category × region |
| `customer_ltv_monthly` | month-end snapshot of each customer's LTV |
| `product_performance_weekly` | weekly rollup per product |
| `cohort_retention` | acquisition-cohort retention matrix |
| `marketing_attribution` | historical campaign → conversion data |
| `competitor_prices_weekly` | external competitor-price feed (weekly crawl) |

**Starter app — "today's orders board":** today's orders + revenue (Cassandra `orders_inflight`) compared against the 30-day daily revenue average (Iceberg `daily_sales_summary`).

---

## IoT — `setup/sample-data/iot/`

DDL files: [`cassandra_schema.cql`](setup/sample-data/iot/cassandra_schema.cql) · [`iceberg_schema.sql`](setup/sample-data/iot/iceberg_schema.sql)

### Cassandra (`iot` keyspace) — hot

| Table | What it holds |
|---|---|
| `device_state_current` | live device state (status, last heartbeat, battery, signal, site) |
| `readings_hot` | last 24h of sensor readings, partitioned by `(device_id, hour bucket)` |
| `alerts_open` | unacknowledged active alerts |
| `device_events_recent` | state changes / commands in last 7 days |
| `topology_current` | device → gateway → site associations right now |

### Iceberg (`iceberg_data.iot`) — cold + analytical + external

| Table | What it holds |
|---|---|
| `readings_archive` | sensor readings older than 24h |
| `hourly_aggregates` | per-device per-metric rollup (min / max / avg / p95 / stddev) |
| `daily_site_summary` | per-site rollup across all devices |
| `failure_history` | labeled device-failure events (training set for ML) |
| `firmware_deployment_history` | which firmware ran on which device when |
| `maintenance_windows` | planned + unplanned outage history |
| `weather_by_location` | external weather feed per site, hourly |

**Starter app — "sensor health dashboard":** per-device last-hour readings (Cassandra `readings_hot` + `device_state_current`) compared against the device's 7-day baseline (Iceberg `hourly_aggregates`). Flag devices that look unusual.

---

## Financial — `setup/sample-data/financial/`

DDL files: [`cassandra_schema.cql`](setup/sample-data/financial/cassandra_schema.cql) · [`iceberg_schema.sql`](setup/sample-data/financial/iceberg_schema.sql)

### Cassandra (`financial` keyspace) — hot

| Table | What it holds |
|---|---|
| `customers` | core customer profile + current risk tier |
| `accounts` | current accounts with live balances |
| `transactions_authorizing` | payment requests being authorized right now |
| `card_transactions_recent` | authorized card activity in last 30 days |
| `card_status_current` | active / blocked / frozen status per card |
| `transfers_pending` | wires / ACH in flight |
| `fraud_alerts_open` | active, unacknowledged fraud cases |

### Iceberg (`iceberg_data.financial`) — cold + analytical + external

| Table | What it holds |
|---|---|
| `transactions_archive` | authorized transactions older than 30 days |
| `account_statements_monthly` | closed monthly statements per account |
| `fraud_training_labels` | confirmed-fraud training set for ML models |
| `risk_assessment_history` | quarterly snapshots of customer risk scores |
| `portfolio_metrics_daily` | daily investment-portfolio rollup per customer |
| `regulatory_filings` | historical SAR / CTR / compliance events |
| `market_data_daily` | external OHLCV market-data feed |

**Starter app — "spend monitor":** a customer's recent card transactions (Cassandra `card_transactions_recent`) compared against their 30-day spend average (Iceberg `transactions_archive` aggregated).

---

## Connecting to the data

Your app needs three connection details:

- **Cassandra:** `host.containers.internal:9042`, username `cassandra`, password `cassandra`
- **Presto (for Iceberg):** check the watsonx.data UI at `https://localhost:9443` (login `ibmlhadmin` / `password`) for the active Presto endpoint and your bearer token
- **Federation:** Presto can query Cassandra too (catalog `cassandra`) — that's how a single SQL statement can join hot and cold data

Your LLM will pick the libraries; you don't have to.
