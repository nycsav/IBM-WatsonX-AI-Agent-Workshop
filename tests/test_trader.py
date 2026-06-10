"""Trader tests — REQ-004..006, REQ-019 (TST-004a..006b, 019a)."""
import uuid
from datetime import date
from decimal import Decimal

from src.agents import researcher, trader
from src.config import Settings
from src.db.repo import InMemoryRepo
from src.market.clock import MarketClock
from src.models import Position
from tests.fixtures import bars as fx

SID = uuid.uuid1()
CFG = Settings()


def log(*a):
    pass


def bullish_note(clock, ticker="UPT"):
    n = researcher.analyze_ticker(clock, ticker)
    n.session_id = SID
    n.shortlisted = True
    return n


def make_clock(universe=None):
    return MarketClock(universe or {"UPT": fx.uptrend()}, 90)


def pos(ticker, asset_class, entry, stop, qty):
    return Position(SID, uuid.uuid1(), uuid.uuid1(), ticker, asset_class,
                    qty, entry, date(2025, 4, 1), stop, stop, entry * 1.2)


def test_setup_complete():                         # TST-004a / AC-4.1
    clock = make_clock()
    s = trader.size_and_check(trader.build_setup(bullish_note(clock), clock, CFG),
                              [], Decimal("100000"), CFG)
    assert s.status == "approved"
    for f in ("ticker", "asset_class", "direction", "entry_price", "quantity",
              "stop_loss", "take_profit", "trail_rule"):
        assert getattr(s, f), f"missing {f}"


def test_reward_risk_2to1():                       # TST-004b / AC-4.2
    clock = make_clock()
    s = trader.build_setup(bullish_note(clock), clock, CFG)
    risk = s.entry_price - s.stop_loss
    reward = s.take_profit - s.entry_price
    assert reward >= 2 * risk - 1e-9


def test_sizing_within_budget():                   # TST-005a / AC-5.1
    clock = make_clock()
    s = trader.size_and_check(trader.build_setup(bullish_note(clock), clock, CFG),
                              [], Decimal("100000"), CFG)
    budget = Decimal("100000") * Decimal("1.0") / 100
    assert Decimal(str(s.entry_price - s.stop_loss)) * s.quantity <= budget


def test_unviable_size_rejected():                 # TST-005b / AC-5.2
    clock = make_clock()
    s = trader.size_and_check(trader.build_setup(bullish_note(clock), clock, CFG),
                              [], Decimal("50"), CFG)   # tiny account
    assert s.status == "rejected" and s.reject_reason == "risk_budget"
    assert s.quantity == 0                              # never shrunk to junk


def test_max_positions_guardrail():                # TST-006a / AC-6.1
    clock = make_clock()
    book = [pos(f"P{i}", "equity", 100.0, 95.0, 1) for i in range(5)]
    s = trader.size_and_check(trader.build_setup(bullish_note(clock), clock, CFG),
                              book, Decimal("100000"), CFG)
    assert (s.status, s.reject_reason) == ("rejected", "max_open_positions")


def test_aggregate_risk_guardrail():               # TST-006a / AC-6.2
    clock = make_clock()
    # Existing book already risks ~2.9% of 100k (2 positions × 1450)
    book = [pos("A", "equity", 100.0, 90.0, 145),
            pos("B", "equity", 100.0, 90.0, 145)]
    s = trader.size_and_check(trader.build_setup(bullish_note(clock), clock, CFG),
                              book, Decimal("100000"), CFG)
    assert (s.status, s.reject_reason) == ("rejected", "aggregate_risk")


def test_class_cap_guardrail():                    # TST-019a / AC-19.1
    cfg = CFG
    clock = make_clock({"COIN": fx.uptrend("COIN", "crypto")})
    # Existing crypto risk = 1000 of total 2400 (41%); adding ~1000 more
    # pushes crypto past its 30% cap while staying under aggregate 3%.
    book = [pos("XBT", "crypto", 100.0, 90.0, 100),     # risk 1000
            pos("EQ1", "equity", 100.0, 90.0, 140)]     # risk 1400
    note = bullish_note(clock, "COIN")
    s = trader.size_and_check(trader.build_setup(note, clock, cfg),
                              book, Decimal("300000"), cfg)
    assert (s.status, s.reject_reason) == ("rejected", "class_risk_cap")


def test_risk_tier_gate():                         # REQ-006 risk profile
    assert not trader.risk_tier_allowed("high")
    assert not trader.risk_tier_allowed("restricted")
    assert trader.risk_tier_allowed("low")
    assert trader.risk_tier_allowed("medium")


def test_run_records_all_outcomes():               # AC-6.1 persistence
    clock = make_clock()
    repo = InMemoryRepo()
    note = bullish_note(clock)
    trader.run([note], [], Decimal("100000"), clock, repo, CFG, log)
    stored = repo.setups(SID)
    assert len(stored) == 1 and stored[0].status == "approved"
