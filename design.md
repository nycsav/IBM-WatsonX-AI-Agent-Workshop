# Design — Multi-Agent Trading System ("TradeCrew")

**Workshop**: watsonx.data shared-cloud workshop · June 10, 2026
**Attendee**: user-31 · **Domain**: Financial
**Inputs**: `Requirements.md` (Draft v3), `SCHEMAS.md`,
`setup/sample-data/financial/cassandra_schema.cql`,
`setup/sample-data/financial/iceberg_schema.sql`
**Status**: Draft v1

---

## 1. Architecture overview

A single Python process (the **orchestrator**) hosts four agent modules
and a shared **market clock**. Hot state lives in the attendee's writable
Cassandra keyspace `financial_user31`; completed trades and audit history
land in the attendee's writable Iceberg schema
`iceberg_data.financial_user31`; all reference/market data is read from
the shared, read-only `iceberg_data.financial_reference` schema via
Presto.

```
                 ┌─────────────────────────────────────────────┐
                 │           Orchestrator (laptop)             │
                 │                                             │
                 │  ┌────────────┐   shortlist   ┌──────────┐  │
                 │  │ Researcher ├──────────────▶│  Trader  │  │
                 │  └─────▲──────┘               └────┬─────┘  │
                 │        │  OHLCV window             │ approved│
                 │        │  (bulk, once)             ▼ setups  │
                 │  ┌─────┴──────┐               ┌──────────┐  │
                 │  │ MarketClock│◀──── ticks ───│ Executor │  │
                 │  └─────▲──────┘               └────┬─────┘  │
                 │        │ bar data                  │ fills  │
                 │        │                           ▼        │
                 │        │                     ┌──────────┐   │
                 │        └────────────────────▶│ Monitor  │   │
                 │                              └──────────┘   │
                 └───────────┬──────────────────────┬──────────┘
                   Presto (HTTPS :443,        Cassandra (TLS :443,
                   bearer token)              endpoint-factory pin)
                             │                      │
        ┌────────────────────┴───────┐   ┌──────────┴───────────────┐
        │ iceberg_data.              │   │ financial_user31         │
        │   financial_reference (RO) │   │  customers, accounts (RO │
        │   market_data_daily        │   │   by convention)         │
        │   portfolio_metrics_daily  │   │  + NEW: research_notes,  │
        │   risk_assessment_history  │   │   trade_setups,          │
        │ iceberg_data.              │   │   positions_open,        │
        │   financial_user31 (RW)    │   │   orders,                │
        │   + NEW: trades_closed     │   │   exit_adjustments       │
        └────────────────────────────┘   └──────────────────────────┘
```

**Concurrency model**: `asyncio` in one process.
- Researcher fans out per-ticker analysis as concurrent tasks (CPU-light,
  all in-memory once the OHLCV window is loaded).
- Monitor runs as a long-lived task ticking with the market clock.
- Trader and Executor are sequential gates (REQ-006/008 invariants are
  enforced single-file — no races on risk budget or buying power).

**Presto discipline** (shared coordinator, 15–30 attendees): at most one
in-flight Presto query at a time; market data is loaded in **one bulk
query per session**, then served from memory. The high-frequency loop
(Monitor, every tick) touches only Cassandra — millisecond key lookups.

---

## 2. The market clock (REQ-013)

The only "live" price source in the cluster is
`financial_reference.market_data_daily` (daily OHLCV per ticker). The
clock replays it:

- **Load once** (session start): one Presto query pulls the full OHLCV
  window for all tickers into an in-memory frame
  `{ticker → [bar(date, o, h, l, c, v), …]}`, date-ascending.
- **Split**: the first `LOOKBACK` days (default 90 trading days) are the
  Researcher's history; the remaining days are the **replay stream**.
- **Tick**: every `TICK_SECONDS` (default 5s) the clock advances one
  trading day. `clock.today()` returns the current simulated date;
  `clock.bar(ticker)` returns that day's bar. All agents share the one
  clock instance → identical view (AC-13.1).
- **No lookahead** (AC-1.2): agents can only request bars ≤ `today()`;
  the clock raises on anything later.

Session end = trader stops it, or the stream is exhausted.

---

## 3. Data design — new tables

### 3.1 Cassandra (keyspace `financial_user31`) — hot state

All tables are partitioned by `session_id` (a client-generated TIMEUUID
per session). Rationale: every hot read in the system is "everything for
the *current* session" — one-partition queries, Cassandra's sweet spot —
and sessions stay separated for REQ-017 (repeatable, distinguishable).
Volumes are tiny (≤ tens of rows per partition), so single-partition
design has no width risk.

```sql
-- Researcher output (REQ-002/003)
CREATE TABLE IF NOT EXISTS research_notes (
    session_id      TIMEUUID,
    note_id         TIMEUUID,
    ticker          TEXT,
    asset_class     TEXT,
    as_of_date      DATE,          -- simulated date (no-lookahead audit)
    direction       TEXT,          -- bullish | bearish | neutral
    momentum        TEXT,          -- e.g. rsi_zone description
    volatility      TEXT,          -- e.g. low | normal | elevated
    conviction      DECIMAL,       -- 0.000–1.000
    rationale       TEXT,          -- plain-language paragraph
    shortlisted     BOOLEAN,
    PRIMARY KEY ((session_id), note_id)
) WITH CLUSTERING ORDER BY (note_id DESC);

-- Trader output (REQ-004/005/006/019)
CREATE TABLE IF NOT EXISTS trade_setups (
    session_id      TIMEUUID,
    setup_id        TIMEUUID,
    note_id         TIMEUUID,      -- audit chain ← research_notes
    ticker          TEXT,
    asset_class     TEXT,
    direction       TEXT,          -- long (v1)
    entry_price     DECIMAL,
    quantity        INT,
    stop_loss       DECIMAL,
    take_profit     DECIMAL,
    trail_rule      TEXT,          -- e.g. 'arm@+1R;trail=1.5xATR'
    risk_amount     DECIMAL,       -- (entry-stop)*qty at setup time
    status          TEXT,          -- proposed|approved|rejected|executed
    reject_reason   TEXT,          -- which guardrail (AC-6.1)
    created_date    DATE,          -- simulated date
    PRIMARY KEY ((session_id), setup_id)
) WITH CLUSTERING ORDER BY (setup_id DESC);

-- Executor output / Monitor working set (REQ-007/009/011)
CREATE TABLE IF NOT EXISTS positions_open (
    session_id      TIMEUUID,
    position_id     TIMEUUID,
    setup_id        TIMEUUID,      -- audit chain ← trade_setups
    ticker          TEXT,
    asset_class     TEXT,
    quantity        INT,
    entry_price     DECIMAL,
    entry_date      DATE,          -- simulated
    stop_loss       DECIMAL,       -- CURRENT stop (monitor raises it)
    initial_stop    DECIMAL,       -- never changes (monotonicity audit)
    take_profit     DECIMAL,
    trail_armed     BOOLEAN,
    current_price   DECIMAL,       -- refreshed every tick (AC-9.2)
    unrealized_pnl  DECIMAL,       -- refreshed every tick
    last_check_date DATE,          -- simulated date of last cycle
    PRIMARY KEY ((session_id), position_id)
);

-- Order log (REQ-007/008)
CREATE TABLE IF NOT EXISTS orders (
    session_id      TIMEUUID,
    order_id        TIMEUUID,
    setup_id        TIMEUUID,
    position_id     TIMEUUID,
    ticker          TEXT,
    side            TEXT,          -- buy | sell
    order_kind      TEXT,          -- entry | exit
    fill_price      DECIMAL,
    quantity        INT,
    fill_date       DATE,          -- simulated
    exit_reason     TEXT,          -- null for entries; REQ-010 enum for exits
    PRIMARY KEY ((session_id), order_id)
) WITH CLUSTERING ORDER BY (order_id DESC);

-- Stop-adjustment trail (AC-11.1 monotonicity evidence, UF-4 audit)
CREATE TABLE IF NOT EXISTS exit_adjustments (
    session_id      TIMEUUID,
    position_id     TIMEUUID,
    adj_id          TIMEUUID,
    adj_date        DATE,          -- simulated
    old_stop        DECIMAL,
    new_stop        DECIMAL,
    reason          TEXT,          -- 'trail_armed' | 'trail_raise'
    PRIMARY KEY ((session_id, position_id), adj_id)
) WITH CLUSTERING ORDER BY (adj_id ASC);
```

> Pre-loaded `customers` and `accounts` are read but **never written**
> (REQ-018). Committed capital is tracked in our own rows (REQ-008), not
> by mutating `accounts.available_balance`.

### 3.2 Iceberg (`iceberg_data.financial_user31`) — cold archive

Created via Presto at session setup (`IF NOT EXISTS`, REQ-017):

```sql
-- Completed round-trips (REQ-012); mirrors reference-table style
CREATE TABLE IF NOT EXISTS iceberg_data.financial_user31.trades_closed (
    session_id      VARCHAR,
    position_id     VARCHAR,
    setup_id        VARCHAR,
    note_id         VARCHAR,       -- full audit chain in one row
    ticker          VARCHAR,
    asset_class     VARCHAR,
    quantity        INTEGER,
    entry_price     DECIMAL(14,4),
    entry_date      DATE,
    exit_price      DECIMAL(14,4),
    exit_date       DATE,
    exit_reason     VARCHAR,       -- stop_loss|take_profit|trailing|trader|session_end
    realized_pnl    DECIMAL(14,2),
    holding_days    INTEGER,
    exit_year       INTEGER,
    exit_month      INTEGER
)
WITH (format = 'PARQUET', partitioning = ARRAY['exit_year','exit_month']);
```

Writes are batched `INSERT INTO ... VALUES` at position close (a few rows
per session — trivial for the shared coordinator).

---

## 4. Data access patterns — per agent, against actual tables

Notation: **[C]** = Cassandra driver (CQL, hot path), **[P]** = Presto
HTTP (federated/analytical). Every [C] read below is a single-partition
query satisfied by the table's partition key — no `ALLOW FILTERING`
anywhere.

### 4.0 Session bootstrap (orchestrator, once)

| # | Purpose | Pattern |
|---|---------|---------|
| B1 | Pick trading account (Open Q1) | **[P]** `SELECT account_id, customer_id, available_balance FROM cassandra.financial_user31.accounts WHERE account_type = 'investment' AND status = 'active' ORDER BY available_balance DESC LIMIT 1` — Presto does the global sort Cassandra can't; runs once, table is only ~1.2k rows. |
| B2 | Risk-profile gate (REQ-006) | **[C]** `SELECT risk_tier, account_status FROM customers WHERE customer_id = ?` — PK lookup. Abort session if tier ∈ {high, restricted}. |
| B3 | Risk-history context (Researcher input) | **[P]** `SELECT risk_score, snapshot_date FROM iceberg_data.financial_reference.risk_assessment_history WHERE customer_id = ? ORDER BY snapshot_date DESC LIMIT 4` — last 4 quarterly snapshots. |
| B4 | Bulk OHLCV load (market clock) | **[P]** `SELECT ticker, asset_class, quote_date, open_price, high_price, low_price, close_price, volume FROM iceberg_data.financial_reference.market_data_daily ORDER BY ticker, quote_date` — **the one big query**; benefits from `quote_year` partition pruning if we bound the window. Loaded into memory; nothing re-reads this table until the next session. |
| B5 | DDL | **[C]** `CREATE TABLE IF NOT EXISTS …` ×5 in `financial_user31`; **[P]** `CREATE TABLE IF NOT EXISTS …` for `trades_closed`. Idempotent (AC-17.1). |

### 4.1 Researcher

| # | Purpose | Pattern |
|---|---------|---------|
| R1 | Per-ticker history | in-memory slice of B4: bars where `quote_date ≤ clock.today()`, last 90. (No-lookahead enforced by the clock, AC-1.2.) Computes SMA-20/50, RSI-14, ATR-14, 20-day realized vol, breakout distance. |
| R2 | Publish notes (REQ-002) | **[C]** `INSERT INTO research_notes (session_id, note_id, ticker, …) VALUES (…)` — one insert per analyzed ticker; `shortlisted = true` for the top K respecting REQ-019 class spread. |
| R3 | Re-research (periodic) | same as R1/R2 at a later `clock.today()`; new `note_id`s, same session partition. |

### 4.2 Trader

| # | Purpose | Pattern |
|---|---------|---------|
| T1 | Read shortlist | **[C]** `SELECT * FROM research_notes WHERE session_id = ?` — single partition; filter `shortlisted` client-side (rows ≤ ~30). |
| T2 | Guardrail state (REQ-006/008/019) | **[C]** `SELECT position_id, asset_class, entry_price, stop_loss, quantity FROM positions_open WHERE session_id = ?` — one partition; concurrency count, aggregate open risk Σ(entry−stop)×qty, per-class risk shares, committed capital — all computed client-side from this one read. |
| T3 | Sizing input | account `available_balance` from B1 (cached) minus committed capital from T2. Risk budget = 1% × balance (REQ-005). |
| T4 | Persist setups | **[C]** `INSERT INTO trade_setups (…, status, reject_reason) VALUES (…)` — `approved` or `rejected` + guardrail name (AC-6.1). |

### 4.3 Executor

| # | Purpose | Pattern |
|---|---------|---------|
| E1 | Pending setups | **[C]** `SELECT * FROM trade_setups WHERE session_id = ?` — filter `status='approved'` client-side. |
| E2 | Fill price (REQ-007, next-bar-open) | in-memory: `clock.bar(ticker).open` of the tick **after** approval — a price the market actually offered (AC-7.1), no same-bar hindsight. |
| E3 | Record fill | **[C]** batch (same partition): `INSERT INTO orders (…)`; `INSERT INTO positions_open (…)`; `UPDATE trade_setups SET status='executed' WHERE session_id=? AND setup_id=?`. Logged batch ⇒ the "atomic step" of FR (AC-7.2/8.x). |

### 4.4 Monitor (every tick — Cassandra only, no Presto)

| # | Purpose | Pattern |
|---|---------|---------|
| M1 | Working set | **[C]** `SELECT * FROM positions_open WHERE session_id = ?` — one partition read per tick (AC-9.1). |
| M2 | Mark to market | in-memory `clock.bar(ticker)`; intraday checks: stop hit if `bar.low ≤ stop` (fill at stop), target hit if `bar.high ≥ take_profit` (fill at target); priority stop → target → trail (REQ-010). |
| M3 | Refresh state (AC-9.2) | **[C]** `UPDATE positions_open SET current_price=?, unrealized_pnl=?, last_check_date=? WHERE session_id=? AND position_id=?`. |
| M4 | Raise stop (REQ-011) | **[C]** `UPDATE positions_open SET stop_loss=?, trail_armed=true WHERE …` + `INSERT INTO exit_adjustments (…, old_stop, new_stop, reason)` — append-only trail proves monotonicity (AC-11.1). |
| M5 | Close position | **[C]** `INSERT INTO orders (…, order_kind='exit', exit_reason=?)`; `DELETE FROM positions_open WHERE session_id=? AND position_id=?`; then **[P]** `INSERT INTO iceberg_data.financial_user31.trades_closed VALUES (…)` (REQ-012; buffered and flushed off the tick path so a slow Presto write never stalls monitoring). |

### 4.5 Snapshot & summary (REQ-021/022/015)

| # | Purpose | Pattern |
|---|---------|---------|
| S1 | Quick-glance snapshot | **[C]** M1 read + **[C]** `SELECT * FROM orders WHERE session_id = ? LIMIT 10` (newest first via clustering order) — assembled and printed; no Presto, never disturbs the session (AC-22.2). |
| S2 | Session summary | **[P]** `SELECT count(*), sum(realized_pnl), avg(holding_days), sum(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) FROM iceberg_data.financial_user31.trades_closed WHERE session_id = ?` + open-position figures from M1. |

### 4.6 The federated centerpiece (REQ-016) — one statement, hot + cold

Mark-to-market the live book against the latest market close **and**
union it with realized history — Cassandra and two Iceberg schemas in a
single Presto query:

```sql
WITH latest AS (
  SELECT ticker, max(quote_date) AS d
  FROM iceberg_data.financial_reference.market_data_daily
  WHERE quote_date <= DATE '<clock.today()>'
  GROUP BY ticker
)
SELECT p.ticker,
       'OPEN'                                   AS state,
       p.quantity,
       p.entry_price,
       m.close_price                            AS mark,
       (m.close_price - p.entry_price) * p.quantity AS pnl
FROM cassandra.financial_user31.positions_open p          -- HOT
JOIN latest l ON l.ticker = p.ticker
JOIN iceberg_data.financial_reference.market_data_daily m -- COLD (shared)
  ON m.ticker = l.ticker AND m.quote_date = l.d
UNION ALL
SELECT t.ticker, 'CLOSED', t.quantity, t.entry_price,
       t.exit_price, t.realized_pnl
FROM iceberg_data.financial_user31.trades_closed t        -- COLD (ours)
ORDER BY state, pnl DESC
```

Run on demand for the demo and as part of S2 (AC-16.1/16.2).

### 4.7 Routing invariant — hot vs. analytical reads

The rule, stated once and enforced everywhere:

> **Hot data is read from Cassandra directly (CQL, single-partition).
> Analytical reads go through Presto — Iceberg tables, or federated
> Iceberg ⋈ Cassandra when live state must join history. Presto is
> never on a latency-critical path; the Cassandra driver is never used
> for scans, sorts, or aggregations.**

Routing audit of every read in §4:

| Read | Store/path | Class | Why it's on the right side |
|---|---|---|---|
| B2 risk-tier gate | Cassandra direct | hot | PK lookup on `customers`. |
| T1 shortlist, T2 guardrail state, E1 pending setups, M1 working set, S1 snapshot | Cassandra direct | hot | Single-partition reads on our session tables; these run every cycle and must be milliseconds. |
| B1 account pick | **Presto over the `cassandra` catalog** | analytical | Global sort across all accounts (`ORDER BY available_balance`) — a scan Cassandra can't do efficiently. Runs once at bootstrap; not a hot path. |
| B3 risk history, B4 OHLCV bulk load | Presto → Iceberg | analytical | History windows and external feed; loaded once per session. |
| S2 session summary | Presto → Iceberg | analytical | Aggregation over `trades_closed`. |
| §4.6 unified P/L | Presto **federated** (Cassandra ⋈ Iceberg ∪ Iceberg) | analytical | The hot+cold join — the workshop centerpiece (REQ-016). |

Writes follow the same split: per-tick state changes (M3/M4/M5
Cassandra writes) are CQL; archival writes (`trades_closed`) are
Presto, buffered off the tick path.

**Enforcement in code**: the Presto client is imported only by
`orchestrator.py` (bootstrap, summary, federated view) and
`setup_tables.py` — never by `agents/monitor.py`, `agents/trader.py`,
or `agents/executor.py`. The Cassandra module exposes only prepared,
partition-keyed statements (no free-form CQL), so an accidental scan
can't be written. A pytest guard asserts these import boundaries.

| REQ | Design element |
|---|---|
| 001–003 | §4.1 R1–R3, market clock no-lookahead (§2), `research_notes` |
| 004–006, 019 | §4.2 T1–T4, `trade_setups.reject_reason`, single-writer Trader gate |
| 007–008, 020 | §4.3 E1–E3 next-bar-open fills, logged batch, auto-approve flow |
| 009–011 | §4.4 M1–M4, `exit_adjustments` monotonic trail |
| 012 | §4.4 M5, `trades_closed` |
| 013 | §2 market clock |
| 014 | every agent emits `[AGENT] msg` log lines at each step above |
| 015, 021, 022 | §4.5 S1–S2 |
| 016 | §4.6 federated query |
| 017 | session_id partitioning; `IF NOT EXISTS` DDL (B5) |
| 018 | writes confined to `financial_user31` (both stores); `customers`/`accounts` read-only |

---

## 6. Tech stack picks

Chosen for the 3-hour timebox, the bundle's existing tooling, and the
workshop's connection constraints. **No code yet — picks only.**

| Layer | Pick | Why |
|---|---|---|
| Language | **Python 3.11+** | The bundle's `.venv` and reference code (`smoke_test.py`) are Python; the proven Cassandra TLS/endpoint-factory pattern already exists in it. |
| Concurrency | **asyncio** (stdlib) | Monitor loop + research fan-out + API in one process; no extra infra. |
| Cassandra client | **`cassandra-driver`** (already in `.venv`) | Required endpoint-factory pin is a documented pattern for this exact driver. |
| Presto client | **`httpx`** (async) — hand-rolled `/v1/statement` poller | Mirrors `smoke_test.py`'s bearer-token + `nextUri` flow; no heavyweight Presto SDK needed. |
| Config | **`python-dotenv`** | `.env` is already the bundle convention. |
| API layer | **FastAPI + Uvicorn** | Serves `openapi.yaml`'s surface with typed models; runs inside the same asyncio loop as the agents. |
| Data models | **Pydantic v2** | One set of typed models shared by agents, API responses, and validation; matches the OpenAPI schemas 1:1. |
| Market math | **stdlib only** (`statistics`, plain loops) | SMA/RSI/ATR over ≤ a few hundred daily bars per ticker doesn't justify pandas/numpy weight. |
| CLI / decision log | **`rich`** | Colored, timestamped agent log lines (REQ-014) and the one-screenful snapshot table (REQ-022). |
| Tests | **pytest** | AC spot-checks: sizing math (REQ-005), stop monotonicity (REQ-011), no-lookahead clock guard (AC-1.2). |
| Tags (OpenAPI / code organization) | `Sessions`, `Research`, `Trading`, `Positions`, `Reporting`, `Audit` | Same six tags group the API operations and the agent module boundaries. |

Explicitly **not** used: pandas/numpy (overkill), an ORM (CQL and Presto
SQL are written directly against the access patterns in §4), Docker/local
services (cloud-variant workshop — everything runs from the laptop venv),
LangChain/agent frameworks (the four agents are plain asyncio modules;
the orchestration is deterministic, not LLM-driven at runtime).

## 7. Module layout & configuration

```
src/
  config.py        # .env loading; defaults (TICK_SECONDS, LOOKBACK, RISK_PCT…)
  db/cassandra.py  # session factory: TLS :443, SNI, RouteEndPointFactory pin
  db/presto.py     # bearer-token mint (~12h cache), /v1/statement nextUri poller
  market/clock.py  # bulk load (B4), replay, bar access, no-lookahead guard
  agents/researcher.py | trader.py | executor.py | monitor.py
  orchestrator.py  # session lifecycle, asyncio loop, decision log, summary
  setup_tables.py  # idempotent DDL (B5)
main.py            # one command: python main.py [--ticks N] [--pace 5]
```

Connection mechanics follow `AGENTS.md` / `smoke_test.py` exactly:
Cassandra via the TLS-passthrough Route on :443 with the
endpoint-factory pin (never dial discovered `10.x:9042` peers); Presto
via Software Hub bearer token + `nextUri` polling; everything
configured from `.env`, nothing hardcoded.

**Failure handling**: Presto 401 → remint token once, then surface;
Presto slow (shared coordinator) → only bootstrap and close/summary
paths touch it, monitor cadence is Cassandra-only; partial close (M5
Cassandra OK, Iceberg insert pending) → closed-trade buffer retries at
next tick and at session end (no monitoring stall, no lost trades).

## 8. Post-exercise extensions (v1.1)

### 8.1 External crypto feed (REQ-019 enablement)
The shared reference feed has no crypto rows. `src/load_crypto.py`
batch-loads real BTC/ETH/SOL daily OHLCV from Coinbase Exchange's
public candles API (no key) into the attendee slice
(`financial_user31.market_data_daily_ext`), clamped to the reference
date window. `load_clock` unions reference + ext in the same single
bulk query; graceful fallback when the ext table is absent.

### 8.2 Perplexity news enrichment (REQ-023)
`src/db/perplexity.py` calls the **Agent API** (`POST /v1/agent`,
`fast-search` preset — web search tool + completion, ~$0.01/note).
Orchestrator fires it as a background task for shortlisted notes only;
results land in `research_notes.news_context` (added column, idempotent
ALTER) via a partition-keyed UPDATE. Same import discipline as Presto:
agents never touch it (design §4.7 extended).

### 8.3 Frontend & deployment (REQ-024)
```
Browser (phone/desktop)
   │ https
   ▼
Vercel — Next.js dashboard (frontend/)        static + client-side polling
   │ fetch → NEXT_PUBLIC_API_BASE (default http://localhost:8031)
   ▼
FastAPI orchestrator (src/api.py, laptop)     + CORS middleware
   │ CQL :443 (hot)        │ Presto HTTPS :443 (analytics)
   ▼                       ▼
Cassandra financial_user31  iceberg_data.financial_user31 + _reference
```
- Dashboard polls `/snapshot`, `/positions`, `/log`, `/pnl`, `/summary`
  every few seconds; Start/Halt/Close buttons wrap the existing API.
- Browsers treat `http://localhost` as a secure context, so the
  Vercel-served page may call the locally-running API on the same
  machine. For remote access, the API moves to a host (Fly/Cloud
  Run/IBM Code Engine) and `NEXT_PUBLIC_API_BASE` is repointed.
- The workshop cluster is temporary; post-teardown the data plane must
  be replaced (watsonx.data SaaS or self-hosted Cassandra+Trino+Iceberg)
  before the dashboard has anything to show.

## 9. Decisions taken on open questions (defaults, reversible)

1. Account: highest-balance active `investment` account (B1).
2. Per-class risk cap: 50%; **crypto tightened to 30%** of aggregate
   open risk (volatility asymmetry — flag to instructor if wrong).
3. Pace: 1 simulated day / 5 s; full session ≈ 2–4 min.
4. Snapshot: on request (`--snapshot` / keypress), auto at session end.
