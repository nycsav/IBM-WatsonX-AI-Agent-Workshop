"""Presto client — bearer token + /v1/statement nextUri polling.

Mirrors setup/lib/smoke_test.py probe_presto. Used ONLY by the
orchestrator (bootstrap, summary, federated view) and setup_tables —
never by agents (design §4.7, enforced by TST-RT1). One in-flight
query at a time (shared coordinator etiquette).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, List, Optional, Tuple

import httpx

from ..config import settings


class PrestoError(RuntimeError):
    pass


class PrestoClient:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_at: float = 0.0
        # Lazy: on py3.9 a Lock binds its event loop at construction, and
        # the client may be built before asyncio.run() starts the real loop.
        self._lock: Optional[asyncio.Lock] = None
        self._http = httpx.AsyncClient(verify=True, timeout=60.0)

    async def _mint(self) -> str:
        r = await self._http.post(
            f"https://{settings.wxd_host}/icp4d-api/v1/authorize",
            json={"username": settings.user, "password": settings.password})
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            raise PrestoError("authorize returned no token")
        self._token, self._token_at = token, time.time()
        return token

    async def token(self) -> str:
        if self._token and time.time() - self._token_at < 11 * 3600:
            return self._token
        return await self._mint()

    async def query(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        """Run one statement to completion. Returns (columns, rows).
        On 401: remint once and retry (design §7 failure handling)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            try:
                return await self._run(sql, await self.token())
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    return await self._run(sql, await self._mint())
                raise

    async def _run(self, sql: str, token: str) -> Tuple[List[str], List[List[Any]]]:
        headers = {"Authorization": f"Bearer {token}",
                   "X-Presto-User": settings.user,
                   "Content-Type": "text/plain"}
        r = await self._http.post(
            f"https://{settings.presto_host}/v1/statement",
            content=sql.encode(), headers=headers)
        r.raise_for_status()
        body = r.json()
        cols: List[str] = []
        rows: List[List[Any]] = []
        for _ in range(2000):                       # generous page cap
            if body.get("columns") and not cols:
                cols = [c["name"] for c in body["columns"]]
            rows.extend(body.get("data") or [])
            state = body.get("stats", {}).get("state")
            if state == "FAILED":
                msg = body.get("error", {}).get("message", "unknown")
                raise PrestoError(f"query failed: {msg[:300]}")
            nxt = body.get("nextUri")
            if not nxt:
                return cols, rows
            r = await self._http.get(nxt, headers=headers)
            r.raise_for_status()
            body = r.json()
        raise PrestoError("query did not finish within page cap")

    async def close(self) -> None:
        await self._http.aclose()
