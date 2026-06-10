"""Researcher tests — REQ-001..003, REQ-019 spread (TST-001a..003b)."""
import uuid

from src.agents import researcher
from src.db.repo import InMemoryRepo
from src.market.clock import MarketClock
from tests.fixtures import bars as fx

SID = uuid.uuid1()
LOGS = []


def log(agent, ticker, msg):
    LOGS.append((agent, ticker, msg))


def make(universe=None, lookback=90):
    return MarketClock(universe or {"UPT": fx.uptrend(),
                                    "SHRT": fx.short_history()}, lookback)


def test_skip_with_reason():                      # TST-001a / AC-1.1
    LOGS.clear()
    repo = InMemoryRepo()
    notes = researcher.run(make(), repo, SID, k=3, log=log)
    tickers = {n.ticker for n in notes}
    assert "UPT" in tickers and "SHRT" not in tickers
    skips = [m for a, t, m in LOGS if t == "SHRT" and "insufficient_history" in m]
    assert skips, "short-history ticker must be skipped WITH a stated reason"


def test_no_class_ignored():                      # TST-001c / AC-1.3
    repo = InMemoryRepo()
    clock = MarketClock(fx.two_class_universe(), 90)
    notes = researcher.run(clock, repo, SID, k=3, log=log)
    assert {"equity", "crypto"} <= {n.asset_class for n in notes}


def test_note_completeness():                     # TST-002a / AC-2.1
    repo = InMemoryRepo()
    notes = researcher.run(make(), repo, SID, k=3, log=log)
    for n in notes:
        assert n.direction in ("bullish", "bearish", "neutral")
        assert n.momentum and n.volatility and n.rationale
        assert len(n.rationale.split()) > 15          # a real explanation
        assert 0.0 <= n.conviction <= 1.0


def test_conviction_data_driven():                # TST-002b / AC-2.2
    """Identical series under different names/classes → same conviction."""
    u = {"AAA": fx.uptrend("AAA", "equity"),
         "BBB": fx.uptrend("BBB", "crypto")}
    repo = InMemoryRepo()
    notes = researcher.run(MarketClock(u, 90), repo, SID, k=2, log=log)
    by = {n.ticker: n.conviction for n in notes}
    assert by["AAA"] == by["BBB"]


def test_shortlist_size_and_rank():               # TST-003a/b
    u = {f"T{i:02d}": fx.uptrend(f"T{i:02d}") for i in range(10)}
    repo = InMemoryRepo()
    notes = researcher.run(MarketClock(u, 90), repo, SID, k=3, log=log)
    short = [n for n in notes if n.shortlisted]
    assert len(short) <= 3
    ranked = sorted(notes, key=lambda n: (-n.conviction, n.ticker))
    assert short[0].conviction == ranked[0].conviction


def test_shortlist_class_breadth():               # REQ-019/AC-2 input side
    repo = InMemoryRepo()
    notes = researcher.run(MarketClock(fx.two_class_universe(), 90),
                           repo, SID, k=2, log=log)
    short = [n for n in notes if n.shortlisted]
    assert {"equity", "crypto"} == {n.asset_class for n in short}


def test_bearish_not_shortlisted():               # long-only v1
    repo = InMemoryRepo()
    notes = researcher.run(MarketClock(fx.two_class_universe(), 90),
                           repo, SID, k=3, log=log)
    assert all(n.direction == "bullish" for n in notes if n.shortlisted)
