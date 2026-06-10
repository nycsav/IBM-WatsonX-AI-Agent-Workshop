"""TradeCrew REST API — implements openapi.yaml (all 14 operations).

Run:  .venv/bin/uvicorn src.api:app --port 8031
The agents stay autonomous (REQ-020); this surface observes and
intervenes (UF-2/UF-3) and serves the audit chain (UF-4).
"""
from __future__ import annotations

import asyncio
import dataclasses
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .orchestrator import Session

app = FastAPI(title="TradeCrew — Multi-Agent Trading System API",
              version="0.1.0")

# REQ-024: the Vercel-hosted dashboard calls this API from the browser.
# Paper-trading workshop app, no credentials — permissive CORS is fine.
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

SESSIONS: Dict[str, Session] = {}
TASKS: Dict[str, asyncio.Task] = {}


# --- error model (openapi.yaml Error schema) ---------------------------------
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 detail: Optional[dict] = None) -> None:
        self.status, self.code, self.message = status, code, message
        self.detail = detail or {}


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status,
                        content={"code": exc.code, "message": exc.message,
                                 "detail": exc.detail})


def get_session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise ApiError(404, "session_not_found", f"unknown session {session_id}")
    return s


def as_dict(obj: Any) -> dict:
    d = dataclasses.asdict(obj)
    return {k: (str(v) if isinstance(v, uuid.UUID) else
                v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in d.items()}


class SessionConfigBody(BaseModel):
    tickSeconds: Optional[float] = None
    maxTicks: Optional[int] = None
    closeAtEnd: bool = True


class HaltBody(BaseModel):
    keepPositions: bool = False


def session_json(s: Session) -> dict:
    return {
        "sessionId": str(s.session_id),
        "state": s.state,
        "startedAt": s.started_at.isoformat(),
        "simulatedDate": str(s.clock.today()) if s.clock else None,
        "accountId": s.account_id,
        "startingBuyingPower": float(s.ledger.starting) if s.ledger else None,
        "remainingBuyingPower": float(s.ledger.remaining) if s.ledger else None,
    }


# --- Health (all connectors) -----------------------------------------------
@app.get("/v1/health")
async def health():
    """Live status of every connector the system depends on."""
    import time as _t
    import httpx as _hx
    from .config import settings as cfg
    from .db import cassandra as cass
    from .db.presto import PrestoClient

    out = {}

    def _ok(name, t0, detail=""):
        out[name] = {"status": "ok", "ms": round((_t.time() - t0) * 1000),
                     "detail": detail}

    def _fail(name, e):
        out[name] = {"status": "fail", "detail": str(e)[:160]}

    t0 = _t.time()                                   # Cassandra (hot store)
    try:
        n = cass.connect().execute(
            "SELECT COUNT(*) FROM accounts").one()[0]
        _ok("cassandra", t0, f"{cfg.keyspace} reachable, accounts={n}")
    except Exception as e:
        _fail("cassandra", e)

    t0 = _t.time()                                   # Presto / watsonx.data
    p = PrestoClient()
    try:
        _, r = await p.query(
            f"SELECT count(*) FROM {cfg.iceberg_schema}.trades_closed")
        _ok("presto_watsonx", t0, f"iceberg reachable, archived trades={r[0][0]}")
    except Exception as e:
        _fail("presto_watsonx", e)
    t0 = _t.time()                                   # crypto ext feed
    try:
        _, r = await p.query(
            f"SELECT count(*) FROM {cfg.iceberg_schema}.market_data_daily_ext")
        _ok("crypto_feed", t0, f"coinbase bars loaded={r[0][0]}")
    except Exception as e:
        _fail("crypto_feed", e)
    finally:
        await p.close()

    t0 = _t.time()                                   # Coinbase public API
    try:
        async with _hx.AsyncClient(timeout=10) as h:
            r = await h.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
            r.raise_for_status()
            _ok("coinbase_api", t0, f"BTC-USD live {r.json().get('price')}")
    except Exception as e:
        _fail("coinbase_api", e)

    t0 = _t.time()                                   # Perplexity Agent API
    import os as _os
    if not _os.environ.get("PERPLEXITY_API_KEY"):
        out["perplexity"] = {"status": "off",
                             "detail": "no key — enrichment disabled (by design)"}
    else:
        try:
            async with _hx.AsyncClient(timeout=20) as h:
                r = await h.post("https://api.perplexity.ai/v1/agent",
                    headers={"Authorization":
                             f"Bearer {_os.environ['PERPLEXITY_API_KEY']}"},
                    json={"preset": "fast-search", "input": "ping",
                          "max_output_tokens": 16})
                r.raise_for_status()
                _ok("perplexity", t0, "agent API authorized")
        except Exception as e:
            _fail("perplexity", e)

    out["overall"] = ("ok" if all(v.get("status") in ("ok", "off")
                                  for v in out.values()) else "degraded")
    return out


# --- Sessions -----------------------------------------------------------------
@app.post("/v1/sessions", status_code=201)
async def start_session(body: Optional[SessionConfigBody] = None):
    if any(s.state == "running" for s in SESSIONS.values()):
        raise ApiError(409, "session_already_running",
                       "a session is already running")
    body = body or SessionConfigBody()
    s = Session()
    SESSIONS[str(s.session_id)] = s
    TASKS[str(s.session_id)] = asyncio.create_task(
        s.run(max_ticks=body.maxTicks, tick_seconds=body.tickSeconds,
              close_at_end=body.closeAtEnd))
    await asyncio.sleep(0)            # let bootstrap begin
    return session_json(s)


@app.get("/v1/sessions")
async def list_sessions():
    return [session_json(s) for s in SESSIONS.values()]


@app.get("/v1/sessions/{session_id}")
async def get_session_route(session_id: str):
    return session_json(get_session(session_id))


@app.post("/v1/sessions/{session_id}/halt")
async def halt_session(session_id: str, body: Optional[HaltBody] = None):
    s = get_session(session_id)
    if s.state == "ended":
        raise ApiError(409, "session_already_ended", "session already ended")
    s.halt(keep_positions=(body or HaltBody()).keepPositions)
    return session_json(s)


# --- Research / Trading / Positions ---------------------------------------------
@app.get("/v1/sessions/{session_id}/research-notes")
async def research_notes(session_id: str, shortlistedOnly: bool = False):
    s = get_session(session_id)
    notes = s.repo.notes(s.session_id)
    if shortlistedOnly:
        notes = [n for n in notes if n.shortlisted]
    return [as_dict(n) for n in notes]


@app.get("/v1/sessions/{session_id}/setups")
async def setups(session_id: str, status: Optional[str] = None):
    s = get_session(session_id)
    out = s.repo.setups(s.session_id)
    if status:
        out = [x for x in out if x.status == status]
    return [as_dict(x) for x in out]


@app.get("/v1/sessions/{session_id}/orders")
async def orders(session_id: str):
    s = get_session(session_id)
    return [as_dict(o) for o in s.repo.orders(s.session_id)]


@app.get("/v1/sessions/{session_id}/positions")
async def positions(session_id: str):
    s = get_session(session_id)
    return [as_dict(p) for p in s.repo.positions(s.session_id)]


@app.post("/v1/sessions/{session_id}/positions/{position_id}/close")
async def close_position(session_id: str, position_id: str):
    s = get_session(session_id)
    ct = s.close_one(position_id)
    if ct is None:
        if any(str(c.position_id) == position_id for c in s.closed):
            raise ApiError(409, "position_already_closed",
                           "position already closed")
        raise ApiError(404, "position_not_found",
                       f"unknown position {position_id}")
    asyncio.create_task(s.flush_closed())
    return as_dict(ct)


# --- Audit ---------------------------------------------------------------------
@app.get("/v1/sessions/{session_id}/trades")
async def trades(session_id: str):
    s = get_session(session_id)
    return [as_dict(c) for c in s.closed]


@app.get("/v1/sessions/{session_id}/trades/{position_id}/audit")
async def audit(session_id: str, position_id: str):
    s = get_session(session_id)
    ct = next((c for c in s.closed if str(c.position_id) == position_id), None)
    if ct is None:
        raise ApiError(404, "position_not_found", "no closed trade for id")
    note = next((n for n in s.repo.notes(s.session_id)
                 if n.note_id == ct.note_id), None)
    setup = next((x for x in s.repo.setups(s.session_id)
                  if x.setup_id == ct.setup_id), None)
    ords = [o for o in s.repo.orders(s.session_id)
            if str(o.position_id) == position_id]
    adjs = s.repo.adjustments(s.session_id, ct.position_id)
    return {
        "note": as_dict(note) if note else None,
        "setup": as_dict(setup) if setup else None,
        "entryOrder": next((as_dict(o) for o in ords
                            if o.order_kind == "entry"), None),
        "adjustments": [as_dict(a) for a in adjs],
        "exitOrder": next((as_dict(o) for o in ords
                           if o.order_kind == "exit"), None),
        "closedTrade": as_dict(ct),
    }


# --- Reporting --------------------------------------------------------------------
@app.get("/v1/sessions/{session_id}/snapshot")
async def snapshot(session_id: str):
    s = get_session(session_id)
    return {
        "simulatedDate": str(s.clock.today()) if s.clock else None,
        "realizedPnlSession": s.realized_pnl(),
        "unrealizedPnlTotal": s.unrealized_pnl(),
        "remainingBuyingPower": float(s.ledger.remaining) if s.ledger else None,
        "openPositions": [as_dict(p) for p in s.repo.positions(s.session_id)],
        "recentDecisions": [
            {"at": ts, "simDate": sim, "agent": agent, "message": msg}
            for ts, sim, agent, msg in s.log_lines[-10:]],
    }


@app.get("/v1/sessions/{session_id}/summary")
async def summary(session_id: str):
    return get_session(session_id).summary()


@app.get("/v1/sessions/{session_id}/pnl")
async def pnl(session_id: str):
    s = get_session(session_id)
    try:
        rows = await s.unified_pnl()
    except Exception as e:
        raise ApiError(502, "upstream_presto_error", str(e)[:300])
    return [{"ticker": r[0], "state": r[1], "quantity": r[2],
             "entryPrice": r[3], "markOrExit": r[4], "pnl": r[5]}
            for r in rows]


@app.get("/v1/sessions/{session_id}/log")
async def decision_log(session_id: str, limit: int = 100):
    s = get_session(session_id)
    return [{"at": ts, "simDate": sim, "agent": agent, "message": msg}
            for ts, sim, agent, msg in s.log_lines[-limit:]][::-1]
