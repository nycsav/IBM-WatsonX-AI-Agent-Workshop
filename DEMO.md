# TradeCrew — 3-minute demo script (T-20)

## Setup (once, already done)
```bash
.venv/bin/python -m src.setup_tables     # idempotent DDL
.venv/bin/python -m pytest tests/ -q     # 33 tests green
```

## The demo

**1. Start the unattended session (≈60s)**
```bash
.venv/bin/python main.py --pace 1
```
Narrate the decision log as it streams: the Researcher scans 20
instruments across 4 asset classes and shortlists 3 with plain-language
rationale; the Trader sizes setups at 1% risk and *rejects* some with
the exact guardrail named (`class_risk_cap` — diversification working);
the Executor fills at next-bar open; the Monitor arms and raises
trailing stops, then banks profits.

**2. Mid-run snapshot (auto-prints at the halfway tick)** — the
busy-trader two-minute check-in: open positions, unrealized P/L, stops,
buying power. One screenful.

**3. The wow line.** When the federated P/L table prints at the end:

> "That table is ONE SQL statement. It joins live open positions sitting
> in **Cassandra** against the latest market closes in **Iceberg**, and
> unions in the closed-trade history we archived to Iceberg — hot store
> and cold store, one query, via Presto on watsonx.data."

Show the same query interactively in the Software Hub UI if time allows
(SQL is in `design.md` §4.6).

**4. (Optional) Intervention via API**
```bash
.venv/bin/uvicorn src.api:app --port 8031 &
curl -X POST localhost:8031/v1/sessions -d '{"tickSeconds": 3}' -H 'Content-Type: application/json'
curl localhost:8031/v1/sessions/<id>/snapshot          # UF-2 check-in
curl -X POST localhost:8031/v1/sessions/<id>/positions/<pid>/close   # UF-3
curl localhost:8031/v1/sessions/<id>/trades/<pid>/audit              # UF-4 full chain
```

## Numbers from the verification run
30 simulated days · 6 trades · 80% win rate · +3,418 realized on a
144k account · exits: 2 trailing, 1 stop-loss, 2 session-end ·
pre-loaded data byte-identical before/after (REQ-018).
