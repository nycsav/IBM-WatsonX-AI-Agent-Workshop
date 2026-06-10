"""Indicator math — stdlib only (design §6). Pure functions over bar lists."""
from __future__ import annotations

import statistics
from typing import List, Optional

from ..models import Bar


def sma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes[-(n + 1):-1], closes[-n:]):
        d = cur - prev
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_loss = sum(losses) / n
    avg_gain = sum(gains) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr(bars: List[Bar], n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-(n + 1):-1], bars[-n:]):
        trs.append(max(cur.high - cur.low,
                       abs(cur.high - prev.close),
                       abs(cur.low - prev.close)))
    return sum(trs) / n


def realized_vol(closes: List[float], n: int = 20) -> Optional[float]:
    """Stdev of daily returns over last n days (fraction, not annualized)."""
    if len(closes) < n + 1:
        return None
    rets = [(b / a) - 1.0 for a, b in zip(closes[-(n + 1):-1], closes[-n:])]
    return statistics.pstdev(rets)


def breakout_distance(bars: List[Bar], n: int = 20) -> Optional[float]:
    """How far today's close sits below the n-day high (fraction; 0 = at high)."""
    if len(bars) < n:
        return None
    high_n = max(b.high for b in bars[-n:])
    if high_n <= 0:
        return None
    return (high_n - bars[-1].close) / high_n
