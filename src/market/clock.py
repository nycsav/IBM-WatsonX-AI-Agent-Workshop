"""Market clock — replays daily OHLCV as the live feed (REQ-013, design §2).

One bulk Presto load per session (B4); after that, all price access is
in-memory. No-lookahead guard: asking for any bar past today() raises.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Dict, List, Optional

from ..models import Bar


class LookaheadError(RuntimeError):
    """An agent asked for data beyond the simulated 'now' (AC-1.2)."""


class MarketClock:
    def __init__(self, bars: Dict[str, List[Bar]], lookback: int) -> None:
        """bars: ticker -> date-ascending daily bars (must be pre-sorted)."""
        self._bars = bars
        self._dates: List[date] = sorted({b.quote_date
                                          for bs in bars.values() for b in bs})
        if lookback >= len(self._dates):
            raise ValueError(
                f"lookback {lookback} >= available days {len(self._dates)}")
        self._idx = lookback              # replay starts after the lookback
        self._classes = {t: bs[0].asset_class for t, bs in bars.items() if bs}

    # --- time ---------------------------------------------------------------
    def today(self) -> date:
        return self._dates[self._idx]

    @property
    def exhausted(self) -> bool:
        return self._idx >= len(self._dates) - 1

    def advance(self) -> date:
        """One trading day forward. Raises StopIteration when exhausted."""
        if self.exhausted:
            raise StopIteration("price stream exhausted")
        self._idx += 1
        return self.today()

    async def run(self, tick_seconds: float, on_tick) -> None:
        """Async tick loop: advance + await on_tick() until exhausted."""
        while not self.exhausted:
            await asyncio.sleep(tick_seconds)
            self.advance()
            await on_tick()

    # --- prices (no lookahead) ------------------------------------------------
    def bar(self, ticker: str, on: Optional[date] = None) -> Optional[Bar]:
        """Bar for ticker on a date (default today). None if not traded."""
        d = on or self.today()
        if d > self.today():
            raise LookaheadError(f"{ticker}@{d} is beyond today {self.today()}")
        for b in self._bars.get(ticker, []):
            if b.quote_date == d:
                return b
        return None

    def history(self, ticker: str, n: int) -> List[Bar]:
        """Last n bars up to and including today — never beyond (AC-1.2)."""
        cutoff = self.today()
        past = [b for b in self._bars.get(ticker, []) if b.quote_date <= cutoff]
        return past[-n:]

    def latest_close(self, ticker: str) -> Optional[float]:
        h = self.history(ticker, 1)
        return h[-1].close if h else None

    # --- universe -------------------------------------------------------------
    def tickers(self) -> List[str]:
        return sorted(self._bars.keys())

    def asset_class(self, ticker: str) -> str:
        return self._classes.get(ticker, "equity")

    def asset_classes(self) -> List[str]:
        return sorted(set(self._classes.values()))


async def load_clock(presto, reference_schema: str, lookback: int) -> MarketClock:
    """B4 — the one bulk query per session."""
    sql = (f"SELECT ticker, asset_class, quote_date, open_price, high_price,"
           f" low_price, close_price, volume"
           f" FROM {reference_schema}.market_data_daily"
           f" ORDER BY ticker, quote_date")
    _, rows = await presto.query(sql)
    bars: Dict[str, List[Bar]] = {}
    for t, ac, qd, o, h, lo, c, v in rows:
        bars.setdefault(t, []).append(
            Bar(t, ac, date.fromisoformat(qd), float(o), float(h),
                float(lo), float(c), int(v or 0)))
    return MarketClock(bars, lookback)
