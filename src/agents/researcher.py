"""Researcher agent — REQ-001..003.

Analyzes every instrument as of clock.today() (no lookahead — the clock
enforces it), emits notes with conviction + plain-language rationale,
shortlists top-K with asset-class breadth (REQ-019 spread preference).
Hot-state writes go through the Repo (Cassandra in prod). No Presto
imports here (design §4.7).
"""
from __future__ import annotations

import uuid
from typing import Callable, Dict, List, Tuple

from ..market import indicators as ind
from ..market.clock import MarketClock
from ..models import ResearchNote, timeuuid

MIN_HISTORY = 51            # SMA-50 needs 50 closes + 1 for returns

Log = Callable[[str, str, str], None]      # (agent, ticker, message)


def analyze_ticker(clock: MarketClock, ticker: str) -> Tuple[ResearchNote, None] or None:
    """Build an (unsaved) note for one ticker, or None+reason if skipped."""
    bars = clock.history(ticker, 90)
    if len(bars) < MIN_HISTORY:
        return None
    closes = [b.close for b in bars]
    s20, s50 = ind.sma(closes, 20), ind.sma(closes, 50)
    r = ind.rsi(closes, 14)
    vol = ind.realized_vol(closes, 20) or 0.0
    bdist = ind.breakout_distance(bars, 20)
    close = closes[-1]

    uptrend = s20 is not None and s50 is not None and s20 > s50
    above = s20 is not None and close > s20

    conviction = 0.5
    direction = "neutral"
    if uptrend:
        conviction += 0.20
        direction = "bullish"
    elif s20 is not None and s50 is not None and s20 < s50:
        conviction -= 0.20
        direction = "bearish"
    if above:
        conviction += 0.10
    if r is not None:
        if 50 <= r <= 70:
            conviction += 0.15
        elif r > 70:
            conviction += 0.05          # overbought — momentum, but stretched
        elif r < 40:
            conviction -= 0.15
    if bdist is not None and bdist <= 0.02:
        conviction += 0.10              # within 2% of 20-day high
    vol_label = "low" if vol < 0.01 else ("normal" if vol < 0.025 else "elevated")
    if vol_label == "elevated":
        conviction -= 0.10
    conviction = max(0.0, min(1.0, round(conviction, 3)))

    momentum = (f"RSI-14 at {r:.0f}" if r is not None else "RSI unavailable")
    rationale = (
        f"{ticker} is in a {'rising' if uptrend else 'falling' if direction == 'bearish' else 'sideways'} "
        f"trend: its 20-day average price is {'above' if uptrend else 'below or near'} the 50-day average, "
        f"and the last close of {close:.2f} is {'above' if above else 'below'} the short-term average. "
        f"Momentum is {'healthy' if r is not None and 50 <= r <= 70 else 'stretched' if r is not None and r > 70 else 'weak'} "
        f"({momentum}), price sits {'' if bdist is None else f'{bdist * 100:.1f}% below the 20-day high, '}"
        f"and day-to-day swings are {vol_label}. "
        f"Overall this earns a conviction of {conviction:.2f} out of 1.")

    return ResearchNote(
        session_id=uuid.UUID(int=0),    # stamped by run()
        note_id=timeuuid(), ticker=ticker,
        asset_class=clock.asset_class(ticker), as_of_date=clock.today(),
        direction=direction, momentum=momentum, volatility=vol_label,
        conviction=conviction, rationale=rationale)


def shortlist(notes: List[ResearchNote], k: int) -> List[ResearchNote]:
    """Top-K by conviction with class breadth (REQ-019/AC-2): pick the best
    note of each distinct class first (round-robin by rank), then fill by
    raw conviction."""
    ranked = sorted(notes, key=lambda n: (-n.conviction, n.ticker))
    picked: List[ResearchNote] = []
    seen_classes: set = set()
    for n in ranked:                              # breadth pass
        if len(picked) >= k:
            break
        if n.asset_class not in seen_classes and n.direction == "bullish":
            picked.append(n)
            seen_classes.add(n.asset_class)
    for n in ranked:                              # fill pass
        if len(picked) >= k:
            break
        if n not in picked and n.direction == "bullish":
            picked.append(n)
    for n in picked:
        n.shortlisted = True
    return picked


def run(clock: MarketClock, repo, session_id: uuid.UUID, k: int,
        log: Log) -> List[ResearchNote]:
    """One research pass over the whole universe (REQ-001/AC-1: every
    ticker analyzed or skipped-with-reason)."""
    notes: List[ResearchNote] = []
    for t in clock.tickers():
        note = analyze_ticker(clock, t)
        if note is None:
            log("RESEARCH", t, "skipped: insufficient_history "
                f"(<{MIN_HISTORY} bars as of {clock.today()})")
            continue
        note.session_id = session_id
        notes.append(note)
    chosen = shortlist(notes, k)
    for n in notes:
        repo.add_note(n)
        if n.shortlisted:
            log("RESEARCH", n.ticker,
                f"conviction {n.conviction:.2f} [{n.asset_class}] SHORTLISTED — "
                f"{n.direction}, {n.momentum}, vol {n.volatility}")
    log("RESEARCH", "*", f"scan of {len(clock.tickers())} instruments across "
        f"classes {clock.asset_classes()} → {len(chosen)} shortlisted")
    return notes
