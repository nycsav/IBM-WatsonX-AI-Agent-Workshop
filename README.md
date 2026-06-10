# TradeCrew — Multi-Agent Trading System

Built spec-first at the **IBM watsonx.data workshop, June 10 2026**
(attendee user-31, financial domain). Four autonomous agents —
**Researcher → Trader → Executor → Monitor** — paper-trade a simulated
live market on a Cassandra (hot) + Iceberg (cold) data fabric federated
by Presto, with strict risk management and a full audit trail.

**Live dashboard**: https://tradecrew-dashboard.vercel.app
*(needs the local API running — see below)*

## The spec stack (read in order)
| File | What it is |
|---|---|
| `Requirements.md` | REQ-001..024 with acceptance criteria, personas, user flows |
| `design.md` | Architecture, data access patterns vs. actual tables, routing invariant |
| `openapi.yaml` | OpenAPI 3.1 — 14 operations, every one mapped to REQ-IDs |
| `todo.md` | Build plan, all 26 tasks checked off |
| `test-plan.md` | Every REQ → a test; 33 passing |
| `DEMO.md` | 3-minute walkthrough |

## Run it
```bash
./setup/connect-workshop.sh <user> '<password>'   # cluster connection + venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m src.setup_tables              # idempotent DDL
.venv/bin/python -m src.load_crypto               # real BTC/ETH/SOL (Coinbase, no key)
.venv/bin/python -m pytest tests/ -q              # 33 tests

.venv/bin/python main.py --pace 1                 # unattended console session
# or with the API + dashboard:
.venv/bin/uvicorn src.api:app --port 8031         # then open the Vercel URL
```
Optional: `PERPLEXITY_API_KEY` in `.env` enriches shortlisted research
notes with live market news (Agent API, ~$0.01/note). Without it the
system runs identically.

## Architecture in one paragraph
A market clock replays the cluster's daily OHLCV as a live feed (no
lookahead). The Researcher scores 23 instruments across 5 asset classes
and shortlists with class breadth; the Trader sizes at 1% risk with
hard guardrails (max positions, 3% aggregate risk, per-class caps,
risk-tier gate) and names the guardrail on every rejection; the
Executor fills at next-bar open under buying-power accounting; the
Monitor marks to market every tick, raises trailing stops monotonically
and exits on stop/target/trail. Hot reads are single-partition
Cassandra CQL; analytics go through Presto — including the
centerpiece: **one federated SQL statement joining live Cassandra
positions to the Iceberg market archive and closed-trade history.**

## Notes
- Paper trading only. The workshop cluster is torn down after the
  event; the data plane must be replaced for the app to run beyond it
  (see `design.md` §8.3).
- Frontend is `frontend/` (Next.js, deployed on Vercel); the dashboard
  calls the API at `NEXT_PUBLIC_API_BASE` (default `http://localhost:8031`).
