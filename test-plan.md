# Test Plan — TradeCrew

Maps every requirement in `Requirements.md` (Draft v3) to concrete
tests. Written before the code; tests are implemented alongside each
todo.md task and must be green before the task is checked off.

**Levels**
- **U** — unit (pytest, pure logic, fixture bars; no cluster needed)
- **I** — integration (pytest, hits the live workshop cluster; marked
  `@pytest.mark.cluster`, skipped when `.env` absent)
- **E** — end-to-end (scripted full session; asserts on artifacts)

**Fixtures** (`tests/fixtures/bars.py`) — hand-built daily bar
sequences with known properties: `UPTREND` (steady rise), `BREAKOUT`
(range then surge), `GAP_DOWN` (opens below prior stop), `RETRACE`
(rises +2R then falls), `FLAT` (no signal), `SHORT_HISTORY` (12 bars),
`TWO_CLASS` (one equity + one crypto ticker). Deterministic — no
randomness, no network.

---

## Research & analysis

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-001a | U | REQ-001/AC-1 | Run researcher over {UPTREND, SHORT_HISTORY}: UPTREND analyzed; SHORT_HISTORY skipped with reason `insufficient_history` recorded — nothing silently dropped. |
| TST-001b | U | REQ-001/AC-2 | Clock at day N: researcher requesting `history(t, n)` never receives a bar dated > N; asking the clock for day N+1 raises `LookaheadError`. |
| TST-001c | U | REQ-001/AC-3 | TWO_CLASS fixture: research notes contain both `equity` and `crypto` rows — no class ignored. |
| TST-002a | U | REQ-002/AC-1 | Every emitted note has non-empty direction, momentum, volatility, rationale; rationale ≥ 1 full sentence and contains no bare indicator codes (regex: must not be only "RSI=61"-style fragments). |
| TST-002b | U | REQ-002/AC-2 | Same fixture series fed as two different tickers in different classes → identical conviction (score depends on data, not identity). |
| TST-003a | U | REQ-003/AC-1 | 10 candidate notes, shortlist size 3 → exactly ≤3 shortlisted. |
| TST-003b | U | REQ-003/AC-2 | Shortlist order == descending conviction order; re-running ranking on the same notes reproduces it exactly. |

## Trade setups & risk

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-004a | U | REQ-004/AC-1 | Every approved setup has all 8 elements non-null (instrument, class, direction, entry, size, stop, target, trail rule). |
| TST-004b | U | REQ-004/AC-2 | For each generated setup: `(target − entry) ≥ 2 × (entry − stop)`. Boundary: engineered fixture where ATR forces exactly 2.0 → still passes. |
| TST-005a | U | REQ-005/AC-1 | Balance 100k, risk 1% → for the generated setup `(entry − stop) × qty ≤ 1000` (exact arithmetic, Decimal). |
| TST-005b | U | REQ-005/AC-2 | High-priced instrument where 1 share risks > budget → setup `rejected`, reason `risk_budget`, NOT a zero/negative quantity. |
| TST-006a | U | REQ-006/AC-1 | Scenario table → expected reject_reason: 6th setup → `max_open_positions`; setup pushing Σrisk > 3% → `aggregate_risk`; risk_tier=high session → `risk_profile` (session-level abort). |
| TST-006b | U | REQ-006/AC-2 | Property check across a scripted session: after every executor/monitor action, open-position count ≤ 5 and Σ(entry−stop)×qty ≤ 3% of balance. |
| TST-019a | U | REQ-019/AC-1 | Crypto candidates totaling > 30% cap → excess crypto setup rejected with `class_risk_cap`; equity beyond 50% likewise. |
| TST-019b | E | REQ-019/AC-2 | Full session on TWO_CLASS data with valid signals in both → positions opened in ≥ 2 asset classes. |

## Execution

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-007a | U | REQ-007/AC-1 | Fill price == the NEXT tick's `open` after approval; assert fill ∈ [bar.low, bar.high] of that bar; approving on the same bar's close is impossible (clock test). |
| TST-007b | U | REQ-007/AC-2 | After fill: one `orders` row (kind=entry) + one `positions_open` row exist and cross-reference (setup_id, position_id). |
| TST-008a | U | REQ-008/AC-1 | Invariant: committed + remaining == starting buying power after every open AND after every close (releases capital). Property-checked over a scripted 6-trade session. |
| TST-008b | U | REQ-008/AC-2 | Setup whose notional > remaining buying power → rejected `insufficient_buying_power`, even when risk budget alone would pass. |
| TST-020a | E | REQ-020/AC-1,2 | Full session driven by `main.py` with stdin closed (no TTY): completes to summary, exit code 0 — proves nothing prompts or blocks. |

## Monitoring, exits & P/L

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-009a | U | REQ-009/AC-1 | Scripted 10-tick run: every open position has `last_check_date` == every simulated date it was open for (no missed cycle). |
| TST-009b | U | REQ-009/AC-2 | After each tick, `current_price`/`unrealized_pnl` equal hand-computed values from the fixture bar. |
| TST-010a | U | REQ-010/AC-1 | Four scripted sequences → exit reasons exactly {stop_loss, take_profit, trailing, session_end}; trader-initiated covered in TST-UF3. |
| TST-010b | U | REQ-010/AC-2 | Bar that touches stop → position closed in THAT cycle, not a later one. GAP_DOWN: opens below stop → fills at stop price (conservative), not at fantasy stop level above open? — fills at min(stop, bar.open) … assert documented conservative rule. |
| TST-010c | U | REQ-010 priority | Engineered bar where low ≤ stop AND high ≥ target in the same bar → stop wins (priority order). |
| TST-011a | U | REQ-011/AC-1 | RETRACE fixture: recorded `exit_adjustments` sequence is strictly non-decreasing in new_stop; trail arms only after +1R. |
| TST-011b | U | REQ-011/AC-2 | RETRACE: final exit price ≥ the highest trailed stop (never exits worse than tightened level). |
| TST-021a | U | REQ-021/AC-1 | Snapshot call between ticks returns P/L without recomputation (figures read from maintained state; no Presto call observed — spy on client). |
| TST-021b | I | REQ-021/AC-2 | Σ realized_pnl from snapshot/summary == Σ `trades_closed.realized_pnl` rows for the session (queried live). |
| TST-012a | I | REQ-012/AC-1 | After an E2E session: every closed position has exactly one `trades_closed` row with all 8 fields non-null. |
| TST-012b | I | REQ-012/AC-2 | Pick a random closed trade → walk note_id ← setup_id ← position_id chain across research_notes, trade_setups, orders, exit_adjustments, trades_closed: complete story reconstructed. |

## Session & observability

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-013a | U | REQ-013/AC-1 | Two concurrent asyncio tasks read clock.today() across 100 ticks → never observe different dates at the same await point. |
| TST-013b | E | REQ-013/AC-2 | Default-pace session yields ≥1 closed trade and finishes < 5 min wall clock. |
| TST-014a | E | REQ-014/AC-1,2 | Parse the captured decision log of an E2E run: every order/exit/adjustment in the DB has a matching log line; each line has timestamp + agent + ticker. |
| TST-022a | U | REQ-022/AC-1 | Snapshot rendering ≤ 30 lines (one screenful); first 5 lines contain session P/L and buying power (most-important-first). |
| TST-022b | U | REQ-022/AC-2 | Request snapshot mid-tick (async) → monitor cycle timing unaffected (no lock contention beyond threshold), no state mutated. |
| TST-015a | E | REQ-015/AC-1,2 | Summary figures (trades, win rate, realized P/L) recomputed independently from `trades_closed` rows match exactly; realized and unrealized reported as separate fields. |
| TST-016a | I | REQ-016/AC-1 | With ≥1 open position: federated query (§4.6) returns one OPEN row per position; `mark` == latest `market_data_daily.close ≤ clock.today()`. |
| TST-016b | I | REQ-016/AC-2 | Same single statement returns CLOSED rows from `trades_closed` in the same result set (UNION verified). |
| TST-017a | I | REQ-017/AC-1 | Run `setup_tables.py` twice, then two consecutive short sessions, no manual cleanup → zero errors. |
| TST-017b | I | REQ-017/AC-2 | Rows from both sessions present and disjoint by session_id in research_notes/orders/trades_closed. |

## Boundaries & routing

| Test ID | Lvl | REQ / AC | Test |
|---|---|---|---|
| TST-018a | I | REQ-018/AC-1 | Capture every keyspace/schema touched by a session (driver-level spy): writes only to `financial_user31` (Cassandra) and `iceberg_data.financial_user31` (Iceberg). |
| TST-018b | I | REQ-018/AC-2 | Checksum `customers` + `accounts` rows (count + sample hash) before and after an E2E session → identical. |
| TST-RT1 | U | design §4.7 | Import guard: `agents/monitor.py`, `agents/trader.py`, `agents/executor.py` do not import `src.db.presto` (AST walk). |
| TST-RT2 | U | design §4.7 | Every prepared CQL statement in `src/db/cassandra.py` includes the partition key in its WHERE clause / is an INSERT — no scans, no `ALLOW FILTERING` (string audit of statement registry). |
| TST-UF3 | I | UF-3, REQ-010 | Mid-session `POST /positions/{id}/close` → position gone from positions_open, trades_closed row exit_reason='trader'; `POST /halt` → no new entries afterward. |

---

## Coverage check (every REQ → at least one test)

REQ-001..003 ✓ (TST-001a..003b) · REQ-004..006 ✓ (004a..006b) ·
REQ-007/008 ✓ (007a..008b) · REQ-009..012 ✓ (009a..012b) ·
REQ-013..018 ✓ (013a..018b) · REQ-019..022 ✓ (019a..022b) ·
UF-3 ✓ (TST-UF3) · routing invariant ✓ (TST-RT1/RT2)

## Execution order & gating

1. **U tests** are written WITH each agent module (todo T-07..T-11) —
   red/green per task; no cluster needed, run in milliseconds.
2. **I tests** run after Phase 1 connections exist; tagged
   `@pytest.mark.cluster`; they respect Presto etiquette (each ≤ 1
   concurrent query; reuse one short session where possible).
3. **E tests** are the Phase 6 gate (todo T-18..T-20): full-session
   runs whose artifacts (log, DB rows, summary) several tests assert
   on — run the session once, assert many times.

Command targets: `pytest -m "not cluster"` (laptop-only, fast loop) ·
`pytest` (everything, needs `.env`) · `pytest tests/test_e2e.py -s`
(demo rehearsal).
