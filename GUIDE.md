# TradeCrew — User Guide & Prompt Cookbook

How to operate the trading agents day-to-day: starting sessions,
placing and exiting trades, tracking P/L, driving it with AI-assistant
prompts, and the roadmap for connecting a real brokerage.

> **Reality check (read first):** TradeCrew is a paper-trading system.
> No real money moves anywhere in this codebase. The "Connecting a
> brokerage" section below describes the supported path to *paper*
> brokerage APIs (Alpaca paper, Coinbase sandbox) — graduating beyond
> that is a deliberate, separate decision with real financial risk.

---

## 1. The three ways to operate it

### A. Console (simplest)
```bash
.venv/bin/python main.py                  # default: 1 simulated day / 5s
.venv/bin/python main.py --pace 1         # demo speed
.venv/bin/python main.py --ticks 20       # cap the session length
```
Everything streams as the decision log; a snapshot prints mid-session;
summary + federated P/L print at the end. Zero interaction required
(REQ-020) — start it before your workday and read the story later.

### B. API (programmable)
```bash
.venv/bin/uvicorn src.api:app --port 8031
```
| Action | Call |
|---|---|
| Start a session | `POST /v1/sessions` body `{"tickSeconds": 5}` |
| Quick check-in (UF-2) | `GET /v1/sessions/{id}/snapshot` |
| Open positions | `GET /v1/sessions/{id}/positions` |
| **Take profit / cut a loss now** | `POST /v1/sessions/{id}/positions/{pid}/close` |
| **Stop everything** | `POST /v1/sessions/{id}/halt` (`{"keepPositions": true}` to only block new entries) |
| Realized trades | `GET /v1/sessions/{id}/trades` |
| Full audit of one trade (UF-4) | `GET /v1/sessions/{id}/trades/{pid}/audit` |
| P/L (hot+cold, one query) | `GET /v1/sessions/{id}/pnl` |
| Session report | `GET /v1/sessions/{id}/summary` |

### C. Dashboard (mobile-friendly)
Run the API (above), then open **https://tradecrew-dashboard.vercel.app**
on the same machine. START SESSION / HALT buttons, per-position *close*
buttons, live P/L, and the agent decision log. (From another device,
the API must be hosted somewhere reachable — see §5.)

---

## 2. How trades get placed (and how to influence them)

You don't place entries by hand — that's the point. The pipeline is:

1. **Researcher** scores every instrument (trend, RSI, volatility,
   breakout) → conviction 0–1 → shortlists top-K across asset classes.
2. **Trader** turns the shortlist into setups: entry at last close,
   stop at 2×ATR, target at 2:1 reward-to-risk, trailing rule armed at
   +1R. Sizing risks ≤1% of the account per trade. Guardrails reject
   anything over 5 open positions, 3% total open risk, or the
   per-class risk cap — and the rejection names the guardrail.
3. **Executor** fills approved setups at the *next* bar's open.
4. **Monitor** owns the exit: stop-loss, take-profit, or trailing stop
   (which only ever tightens). You never have to decide when to sell —
   but you *can* override (close/halt, §1B/C).

**Tuning the risk appetite** — env vars (set in `.env` or the shell):
| Variable | Default | Meaning |
|---|---|---|
| `RISK_PCT` | 1.0 | % of account risked per trade |
| `AGG_RISK_PCT` | 3.0 | max % of account at risk across all open trades |
| `MAX_POSITIONS` | 5 | max concurrent positions |
| `SHORTLIST` | 3 | candidates per research pass |
| `LOOKBACK` | 90 | research history window (days) |
| `TICK_SECONDS` | 5 | wall-clock seconds per simulated day |

Conservative profile: `RISK_PCT=0.5 AGG_RISK_PCT=2 MAX_POSITIONS=3`.

---

## 3. P/L tracking

**Live (during a session):** snapshot endpoint / dashboard cards show
realized vs unrealized P/L and remaining buying power, continuously
maintained (REQ-021) — never recomputed on demand.

**The federated view (the watsonx.data showcase):** one SQL statement
marks the live Cassandra book against Iceberg's latest closes AND
unions realized history — run it via `GET …/pnl`, the dashboard card,
or directly in the Software Hub UI (SQL in `design.md` §4.6).

**Across sessions (the weekend review):** query your Iceberg archive in
the Software Hub UI:
```sql
-- per-session scorecard
SELECT session_id, count(*) trades, sum(realized_pnl) pnl,
       avg(holding_days) avg_hold,
       sum(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) wins
FROM iceberg_data.financial_user31.trades_closed
GROUP BY session_id ORDER BY max(exit_date) DESC;

-- which exit type makes the money?
SELECT exit_reason, count(*) n, sum(realized_pnl) pnl
FROM iceberg_data.financial_user31.trades_closed GROUP BY exit_reason;

-- per asset class (is diversification paying?)
SELECT asset_class, count(*) n, sum(realized_pnl) pnl
FROM iceberg_data.financial_user31.trades_closed GROUP BY asset_class;
```

**Audit any single trade:** `GET …/trades/{pid}/audit` reconstructs
research note → setup → entry → every stop adjustment → exit.

---

## 4. Prompt cookbook — driving TradeCrew with an AI assistant

These are prompts that work well with Claude Code (or any agent tool)
opened in this repo. The assistant reads `AGENTS.md`/`README.md` and
has everything it needs.

**Operating**
- *"Start a trading session at demo pace and narrate the decision log
  back to me when it finishes."*
- *"Start the API and a session, then give me a snapshot every couple
  of minutes until something closes."*
- *"Halt the session but let the monitor manage the open positions to
  plan."* (→ `halt {keepPositions: true}`)
- *"Close the ETH position now and tell me what it realized."*

**Analysis & review**
- *"Pull the audit chain for my biggest losing trade this session and
  explain, step by step, why the system entered and exited where it
  did."*
- *"Query trades_closed across all sessions and tell me: win rate by
  exit reason, P/L by asset class, and whether the trailing stop is
  earning its keep vs plain take-profits."*
- *"Compare the last two sessions' summaries. What changed?"*

**Tuning (spec-first — keep the docs honest)**
- *"Lower the per-trade risk to 0.5% and rerun. Update Requirements.md
  REQ-005's default and note the change."*
- *"Add a max-holding-period exit (close anything held > 15 simulated
  days). Spec it as REQ-025 with acceptance criteria, add the test,
  then implement."*
- *"The crypto class cap is 30%. Show me how often it actually binds,
  then recommend keeping or changing it."*

**Extending**
- *"Wire a Slack/email notification when any position closes."* (n8n
  or SMTP — off the tick path, like the Iceberg flush.)
- *"Add short-selling support. Start by listing every requirement and
  invariant that assumes long-only."*

---

## 5. Connecting a brokerage (the supported path)

The Executor and Monitor were built behind narrow interfaces, so a
brokerage adapter replaces the simulation without touching agent
logic. The intended ladder — **each rung is a deliberate step**:

```
Rung 1 (you are here)  Replay simulation — workshop/own data, zero risk
Rung 2                 Live PRICES, paper fills — swap MarketClock for a
                       polling feed (Coinbase public, Polygon, Alpaca data);
                       fills stay simulated. No keys with money behind them.
Rung 3                 PAPER brokerage — Alpaca paper-trading API
                       (paper-api.alpaca.markets): real order lifecycle,
                       fake money. Executor adapter maps our setups to
                       bracket orders (entry + stop + target in one);
                       Monitor reconciles fills instead of simulating them.
Rung 4                 Real money. Not a code change — a risk decision.
                       Requires everything in "Before rung 4" below.
```

**What the Alpaca paper adapter looks like** (rung 3, ~a day of work):
- `.env`: `ALPACA_KEY_ID`, `ALPACA_SECRET`, `ALPACA_BASE=https://paper-api.alpaca.markets`
- `src/db/broker.py`: `place_bracket(setup) -> order_id`,
  `get_fills() -> [...]`, `replace_stop(order_id, new_stop)`,
  `close_position(symbol)` — the four calls our agents already need.
- Executor: on approval, submit a **bracket order** (market entry +
  stop-loss + take-profit legs) instead of writing a simulated fill;
  record the broker order id in our `orders` table.
- Monitor: poll fills/positions; trailing-stop raises become
  `replace_stop` calls; everything still lands in `trades_closed` so
  ALL the P/L tracking in §3 keeps working unchanged.
- Crypto: Alpaca paper supports BTC/ETH; Coinbase Advanced Trade API
  (the third API you suggested) is the alternative for crypto-only,
  with a sandbox environment for paper testing.

**Before rung 4 (real money) — non-negotiables:**
- Kill-switch: a halt that cancels every working order at the broker.
- Reconciliation: broker state is truth; our tables must match it on
  every cycle, and mismatches must halt trading, not guess.
- Idempotent order submission (client order ids) so a retry can't
  double-buy. Hard daily-loss circuit breaker. Real fees/slippage in
  the P/L math (currently out of scope #10).
- A long paper track record you've actually reviewed via §3 — and an
  honest read of your jurisdiction's rules. Nothing here is financial
  advice.

---

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Cassandra connect hangs but Presto works | Driver dialing internal pod IPs — the endpoint-factory pin in `src/db/cassandra.py` handles this; see `docs/getting-unstuck.md`. |
| Presto 401s after a long break | Bearer token expired (~12h) — client remints once automatically; persistent 401 → re-run `connect-workshop.sh`. |
| `risk tier 'high' is blocked` at bootstrap | Working as designed (REQ-006) — the account picker excludes high/restricted owners; if it aborts, no eligible account exists. |
| Dashboard: "API unreachable" | Start the API (`uvicorn src.api:app --port 8031`) on the same machine as the browser, or host it and set `NEXT_PUBLIC_API_BASE`. |
| No crypto instruments | Run `.venv/bin/python -m src.load_crypto` (one-time, idempotent). |
| No news on research notes | `PERPLEXITY_API_KEY` missing from `.env` — enrichment degrades silently by design (REQ-023). |
| Everything dead after the workshop | The cluster was torn down — see `design.md` §8.3 for the data-plane replacement options. |
