"""Executor + Monitor tests — REQ-007..011 (TST-007a..011b)."""
import uuid
from decimal import Decimal

from src.agents import executor, monitor, researcher, trader
from src.agents.executor import Ledger
from src.config import Settings
from src.db.repo import InMemoryRepo
from src.market.clock import MarketClock
from tests.fixtures import bars as fx

CFG = Settings()


def log(*a):
    pass


def open_one(universe, ticker, lookback=90, balance="100000"):
    """research → trade → advance one tick → execute. Returns full context."""
    sid = uuid.uuid1()
    repo = InMemoryRepo()
    clock = MarketClock(universe, lookback)
    note = researcher.analyze_ticker(clock, ticker)
    note.session_id = sid
    note.shortlisted = True
    setups = trader.run([note], [], Decimal(balance), clock, repo, CFG, log)
    ledger = Ledger(Decimal(balance))
    clock.advance()                                   # fills are next-bar (E2)
    opened = executor.run(setups, clock, repo, ledger, log)
    index = {s.setup_id: (s.note_id, s.trail_rule) for s in setups}
    return sid, repo, clock, ledger, opened, index


def test_fill_at_next_bar_open():                  # TST-007a / AC-7.1
    sid, repo, clock, ledger, opened, _ = open_one({"UPT": fx.uptrend()}, "UPT")
    assert len(opened) == 1
    bar = clock.bar("UPT")
    assert opened[0].entry_price == bar.open
    assert bar.low <= opened[0].entry_price <= bar.high


def test_fill_records_order_and_position():        # TST-007b / AC-7.2
    sid, repo, clock, ledger, opened, _ = open_one({"UPT": fx.uptrend()}, "UPT")
    orders = repo.orders(sid)
    poss = repo.positions(sid)
    assert len(orders) == 1 and len(poss) == 1
    assert orders[0].position_id == poss[0].position_id
    assert orders[0].setup_id == poss[0].setup_id


def test_ledger_invariant_through_lifecycle():     # TST-008a / AC-8.1
    sid, repo, clock, ledger, opened, index = open_one(
        {"UPT": fx.uptrend()}, "UPT")
    start = ledger.starting
    assert ledger.committed + ledger.remaining == start
    monitor.close_all(clock, repo, ledger, sid, index, "session_end", log)
    assert ledger.committed == Decimal("0")
    assert ledger.remaining == start


def test_insufficient_buying_power_rejected():     # TST-008b / AC-8.2
    sid = uuid.uuid1()
    repo = InMemoryRepo()
    clock = MarketClock({"UPT": fx.uptrend()}, 90)
    note = researcher.analyze_ticker(clock, "UPT")
    note.session_id = sid
    note.shortlisted = True
    setups = trader.run([note], [], Decimal("100000"), clock, repo, CFG, log)
    clock.advance()
    tiny = Ledger(Decimal("10"))                       # can't afford 1 share
    opened = executor.run(setups, clock, repo, tiny, log)
    assert opened == [] and setups[0].status == "rejected"
    assert setups[0].reject_reason == "insufficient_buying_power"


def run_to_exit(universe, ticker, lookback=90, max_ticks=500):
    sid, repo, clock, ledger, opened, index = open_one(universe, ticker,
                                                       lookback)
    assert opened, "fixture must produce a fill"
    closed = []
    ticks = 0
    while not clock.exhausted and not closed and ticks < max_ticks:
        clock.advance()
        closed = monitor.tick(clock, repo, ledger, sid, index, log)
        ticks += 1
    return sid, repo, clock, closed


def test_stop_loss_exit_same_cycle():              # TST-010a/b
    sid, repo, clock, closed = run_to_exit({"GAP": fx.gap_down()}, "GAP")
    assert closed and closed[0].exit_reason == "stop_loss"
    # gap-down: fill at the (worse) open, not at the fantasy stop level
    crash_bar = clock.bar("GAP")
    assert closed[0].exit_price <= crash_bar.open + 1e-9
    assert repo.positions(sid) == []                  # closed THIS cycle


def test_take_profit_exit():                        # TST-010a
    sid, repo, clock, closed = run_to_exit({"UPT": fx.uptrend(days=200)},
                                           "UPT")
    assert closed and closed[0].exit_reason in ("take_profit", "trailing")


def test_priority_stop_over_target():               # TST-010c
    """Bar that touches both stop and target in one day → stop wins."""
    from src.models import Bar, Position
    from datetime import date
    p = Position(uuid.uuid1(), uuid.uuid1(), uuid.uuid1(), "X", "equity",
                 10, 100.0, date(2025, 1, 1), 95.0, 95.0, 110.0)
    wild = Bar("X", "equity", date(2025, 1, 2), 100.0, 111.0, 94.0, 100.0, 1)
    reason, fill = monitor.check_exit(p, wild)
    assert reason == "stop_loss"


def test_trailing_monotonic_and_protects():         # TST-011a/b
    sid, repo, clock, closed = run_to_exit({"RTR": fx.retrace()}, "RTR")
    assert closed, "retrace fixture must close"
    ct = closed[0]
    assert ct.exit_reason == "trailing"
    adjs = repo.adjustments(sid, ct.position_id)
    assert adjs, "trail must have armed"
    stops = [a.old_stop for a in adjs] + [adjs[-1].new_stop]
    assert all(b >= a - 1e-9 for a, b in zip(stops, stops[1:]))   # AC-11.1
    assert adjs[0].reason == "trail_armed"
    # AC-11.2: exit no worse than the final tightened level (gap tolerance:
    # fill may be the bar open just below the trail on the trigger day)
    assert ct.exit_price >= adjs[-1].new_stop * 0.97
    assert ct.realized_pnl > 0                       # kept most of the move


def test_monitor_refreshes_every_position():        # TST-009a/b / AC-9.1/2
    sid, repo, clock, ledger, opened, index = open_one(
        {"FLT": fx.flat()}, "FLT")
    for _ in range(5):
        clock.advance()
        monitor.tick(clock, repo, ledger, sid, index, log)
        for p in repo.positions(sid):
            assert p.last_check_date == clock.today()
            bar = clock.bar("FLT")
            assert p.current_price == bar.close
            assert abs(p.unrealized_pnl -
                       (bar.close - p.entry_price) * p.quantity) < 0.01
