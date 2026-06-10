"""Deterministic bar fixtures (test-plan.md). No randomness, no network."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

from src.models import Bar


def _mk(ticker: str, asset_class: str, closes: List[float],
        start: date = date(2025, 1, 1), spread: float = 0.01) -> List[Bar]:
    """Bars from a close series; open=prev close, high/low pad by spread."""
    bars = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        hi = max(o, c) * (1 + spread)
        lo = min(o, c) * (1 - spread)
        bars.append(Bar(ticker, asset_class, start + timedelta(days=i),
                        round(o, 4), round(hi, 4), round(lo, 4),
                        round(c, 4), 1000))
        prev = c
    return bars


def uptrend(ticker: str = "UPT", asset_class: str = "equity",
            days: int = 120) -> List[Bar]:
    """Steady riser: +0.4%/day. Bullish everything."""
    return _mk(ticker, asset_class, [100 * (1.004 ** i) for i in range(days)])


def flat(ticker: str = "FLT", asset_class: str = "equity",
         days: int = 120) -> List[Bar]:
    """No signal: oscillates ±0.5% around 100, deterministic."""
    closes = [100 + (0.5 if i % 2 == 0 else -0.5) for i in range(days)]
    return _mk(ticker, asset_class, closes)


def downtrend(ticker: str = "DWN", asset_class: str = "equity",
              days: int = 120) -> List[Bar]:
    return _mk(ticker, asset_class, [100 * (0.996 ** i) for i in range(days)])


def short_history(ticker: str = "SHRT", asset_class: str = "equity") -> List[Bar]:
    return _mk(ticker, asset_class, [100 + i for i in range(12)])


def gap_down(ticker: str = "GAP", asset_class: str = "equity") -> List[Bar]:
    """100 days rising, then one day gapping open far below any stop."""
    closes = [100 * (1.003 ** i) for i in range(100)]
    bars = _mk(ticker, asset_class, closes)
    last = bars[-1]
    crash_day = last.quote_date + timedelta(days=1)
    crash_open = last.close * 0.80
    bars.append(Bar(ticker, asset_class, crash_day, round(crash_open, 4),
                    round(crash_open * 1.01, 4), round(crash_open * 0.97, 4),
                    round(crash_open * 0.99, 4), 1000))
    return bars


def retrace(ticker: str = "RTR", asset_class: str = "equity") -> List[Bar]:
    """Entry lands at replay start (~day 91); the rise continues just long
    enough to arm the trail (+1R ≈ +6% with this fixture's ATR) without
    reaching the 2R take-profit (~+12%), then declines — so the exit MUST
    be the trailing stop, banking most of the gain."""
    up = [100 * (1.01 ** i) for i in range(99)]
    peak = up[-1]
    down = [peak * (0.985 ** i) for i in range(1, 36)]
    return _mk(ticker, asset_class, up + down)


def two_class_universe() -> Dict[str, List[Bar]]:
    """One bullish equity + one bullish crypto + one bearish equity."""
    return {
        "UPT": uptrend("UPT", "equity"),
        "COIN": uptrend("COIN", "crypto"),
        "DWN": downtrend("DWN", "equity"),
    }
