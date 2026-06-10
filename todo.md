# TODO — TradeCrew build plan

Derived from `Requirements.md` (Draft v3), `design.md` (Draft v1),
`openapi.yaml` (0.1.0). Tasks are ordered so every phase ends in
something runnable/demoable. Check off only when the listed
verification passes.

---

## Phase 0 — Skeleton & config

- [x] **T-01 Project skeleton** — create `src/` layout per design §7
      (`config.py`, `db/`, `market/`, `agents/`, `orchestrator.py`,
      `setup_tables.py`, `main.py`), `tests/`, `requirements.txt`
      (httpx, fastapi, uvicorn, pydantic, python-dotenv, rich, pytest;
      cassandra-driver already in `.venv`).
      *Verify*: `python -c "import src"` runs from the venv.
- [x] **T-02 Config module** — `src/config.py` loads `.env` + defaults
      (TICK_SECONDS=5, LOOKBACK=90, SHORTLIST=3, RISK_PCT=1.0,
      AGG_RISK_PCT=3.0, MAX_POSITIONS=5, CLASS_CAPS={default:50, crypto:30}).
      → REQ-013, design §8.
      *Verify*: prints resolved config; no secrets hardcoded anywhere.

## Phase 1 — Connections (mirror smoke_test.py exactly)

- [x] **T-03 Cassandra client** — `src/db/cassandra.py`: TLS :443, SNI,
      `check_hostname=False`, **RouteEndPointFactory pin** (AGENTS.md
      detail #4), auth from `.env`, keyspace `financial_user31`.
      → design §7, NFR-2.
      *Verify*: `SELECT COUNT(*) FROM customers` returns 1184-ish in <2s,
      no connect stall.
- [x] **T-04 Presto client** — `src/db/presto.py`: bearer mint via
      `/icp4d-api/v1/authorize` (cache ~12h, remint-once on 401),
      `/v1/statement` POST + `nextUri` polling, `X-Presto-User` header.
      → design §7 failure handling.
      *Verify*: `SHOW SCHEMAS FROM iceberg_data` lists financial_user31.
- [x] **T-05 Table DDL** — `src/setup_tables.py`: 5 Cassandra tables
      (research_notes, trade_setups, positions_open, orders,
      exit_adjustments) + Iceberg trades_closed, all `IF NOT EXISTS`
      per design §3. → REQ-017, REQ-018.
      *Verify*: run twice back-to-back, zero errors (AC-17.1); tables
      visible in Software Hub UI.

## Phase 2 — Market clock (the simulation heart)

- [x] **T-06 Bulk OHLCV load** — B4 query into
      `{ticker → [bars asc]}`; discover tickers + asset classes
      (REQ-001/AC-3: log every class found).
      *Verify*: log line "loaded N tickers / M bars / classes: …".
- [x] **T-07 Clock replay** — `clock.today()`, `clock.bar(t)`,
      `clock.history(t, n)`, lookback/replay split, async tick task,
      **no-lookahead guard raises** on future dates. → REQ-013, AC-1.2.
      *Verify (pytest)*: requesting tomorrow's bar raises; two tasks
      reading concurrently see the same date (AC-13.1).

## Phase 3 — Agents

- [x] **T-08 Researcher** — SMA-20/50, RSI-14, ATR-14, 20d vol,
      breakout distance → conviction 0–1 + plain-language rationale;
      shortlist top-K **with class spread** (REQ-019/AC-2); insert
      research_notes (R2); skip-with-reason on short history (AC-1.1).
      → REQ-001..003.
      *Verify (pytest)*: known fixture series → expected direction +
      conviction; shortlist ≤ K and ≥2 classes when available.
- [x] **T-09 Trader** — guardrail read T2 (one partition), sizing
      (1% risk; reject if min size breaches — AC-5.2), 2:1 R:R target
      (AC-4.2), guardrails: max positions, agg risk, class caps,
      risk_tier gate (B2); persist approved/rejected + reject_reason.
      → REQ-004..006, 019.
      *Verify (pytest)*: table of guardrail scenarios → correct
      reject_reason each (AC-6.1); sizing math exact (AC-5.1).
- [x] **T-10 Executor** — next-tick-open fills (E2, AC-7.1), batch
      write orders+positions_open+setup status (E3), buying-power
      ledger (REQ-008: committed+remaining == starting, AC-8.1).
      *Verify (pytest)*: fill price == next bar open; ledger invariant
      holds across opens/closes; insufficient power → reject (AC-8.2).
- [x] **T-11 Monitor** — per-tick cycle M1–M5: refresh price/uPnL
      (AC-9.2), exit priority stop→target→trail (REQ-010), trail
      arm@+1R / raise-never-lower + exit_adjustments rows (REQ-011),
      close → orders(exit) + delete + buffered Iceberg trades_closed
      flush off tick path (M5, REQ-012).
      *Verify (pytest)*: scripted bar sequences hit each exit reason in
      the right cycle (AC-10.2); stop sequence monotonic (AC-11.1);
      gap-down day fills at stop (conservative).

## Phase 4 — Orchestrator & observability

- [x] **T-12 Orchestrator** — session lifecycle (TIMEUUID session_id),
      B1 account pick + B2 gate, research → trade → execute pipeline +
      monitor loop, periodic re-research, halt/end states, zero
      prompts (REQ-020/AC-1). → design §1.
      *Verify*: `python main.py` runs a full unattended session to
      summary with ≥1 closed trade in <5 min.
- [x] **T-13 Decision log** — rich console: `[12:01:14 d=2025-08-12]
      RESEARCH AAPL conviction 0.82: …` for every material decision.
      → REQ-014.
      *Verify*: read the log of a run aloud — the story is complete
      (AC-14.1).
- [x] **T-14 Snapshot & summary** — S1 (Cassandra-only snapshot table,
      one screenful, REQ-021/022) + S2 summary (win rate, realized vs
      unrealized, max drawdown) printed at session end (REQ-015).
      *Verify*: snapshot under one screen; summary totals reconcile
      with trades_closed rows (AC-15.1/21.2).
- [x] **T-15 Federated P/L query** — §4.6 statement wired up
      (REQ-016): hot positions_open ⋈ market_data_daily ∪ trades_closed.
      *Verify*: run mid-session with ≥1 open and ≥1 closed trade —
      one result set shows both, marks match clock prices (AC-16.1/2).

## Phase 5 — API layer (openapi.yaml surface)

- [x] **T-16 FastAPI app** — all 14 operations, Pydantic models
      mirroring openapi.yaml schemas, Error model with machine codes,
      404/409/422/502/504 mapping. → openapi.yaml.
      *Verify*: `GET /v1/sessions/{id}/snapshot` + `/pnl` against a
      live session; FastAPI's generated spec diff vs openapi.yaml —
      no missing operations.
- [x] **T-17 Intervention endpoints** — `POST …/halt`,
      `POST …/positions/{id}/close` (UF-3; exit_reason=trader).
      *Verify*: close one position mid-run via curl; trades_closed row
      has exit_reason='trader'.

## Phase 6 — Acceptance & demo

- [x] **T-18 AC test sweep** — pytest suite green per `test-plan.md`
      (every REQ has at least one passing test).
- [x] **T-21 Routing invariant check** — design §4.7: hot reads are
      Cassandra-direct single-partition; analytics are Presto
      (Iceberg or federated). Pytest guard: `agents/monitor|trader|
      executor` never import the Presto client; Cassandra module
      exposes only partition-keyed prepared statements.
      *Verify*: guard test green + grep shows no Presto import in agents/.
- [x] **T-19 Repeatability** — two consecutive sessions, no cleanup
      (AC-17.1); both sessions queryable by session_id (AC-17.2);
      pre-loaded customers/accounts untouched (AC-18.2).
- [x] **T-20 Demo script** — 3-minute walkthrough: start session →
      watch decision log → mid-run snapshot → federated P/L query in
      Software Hub UI → summary. Note the wow-line: "one SQL statement
      joins live Cassandra positions to the Iceberg archive."

## Phase 7 — Post-exercise extensions (v3.2 scope)

- [x] **T-22 Crypto feed** — Coinbase public candles → ext Iceberg table,
      clock union. → REQ-019. *Verified*: ETH traded + take-profit'd live.
- [x] **T-23 Perplexity enrichment** — Agent API news_context on
      shortlisted notes, background task, silent degrade. → REQ-023.
      *Verified*: live June-10 news on AUD/USD, BTC, CORP-IG, ETH notes.
- [x] **T-24 CORS on FastAPI** — dashboard origin can call the API.
      *Verify*: browser fetch from Vercel origin succeeds.
- [x] **T-25 Next.js dashboard (frontend/)** — snapshot, positions, log,
      P/L, Start/Halt/Close buttons; phone-sized layout. → REQ-024.
      *Verify*: renders live session; close button produces
      exit_reason='trader'.
- [x] **T-26 Vercel deploy** — `vercel --prod`; NEXT_PUBLIC_API_BASE
      env; README note. *Verify*: public URL renders against local API.

---

## Stretch (only if time remains)

- [ ] **S-01** Operator approval mode for setups (Open Q3 alternative).
- [ ] **S-02** `agent_run_log` Iceberg table (full decision audit).
- [ ] **S-03** Auto-refreshing snapshot (Open Q4 alternative).

## Deliberately not doing (per Requirements.md §5)

Options/RWA data, live trading-loop feeds, shorting, ML models, native
mobile app, fees/slippage, auth, cluster admin. (Web dashboard and
batch crypto/news feeds moved INTO scope in v3.2 — see Phase 7.)
