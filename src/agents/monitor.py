"""Monitor agent — REQ-009..012, REQ-021.

Every tick (M1–M5): refresh price/uPnL on every open position, enforce
exits in priority order stop → target → trail (REQ-010), arm/raise the
trailing stop monotonically (REQ-011), close positions and hand the
ClosedTrade to a buffer the orchestrator flushes to Iceberg off the
tick path (M5). Cassandra-only — no Presto imports (design §4.7).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Callable, List, Optional, Tuple

from ..market.clock import MarketClock
from ..models import (Bar, ClosedTrade, ExitAdjustment, Order, Position,
                      TradeSetup, timeuuid)
from .executor import Ledger

Log = Callable[[str, str, str], None]


def _trail_distance(trail_rule: str) -> float:
    """Parse the numeric trail width from 'arm@+1R;trail=1.5xATR=4.2300'."""
    try:
        return float(trail_rule.rsplit("=", 1)[1])
    except (IndexError, ValueError):
        return 0.0


def check_exit(p: Position, bar: Bar) -> Optional[Tuple[str, float]]:
    """REQ-010 priority on today's bar: stop → target. (Trail raises are
    handled after — a raised trail can only fire on a LATER bar.)
    Conservative fills: gap through a level fills at the open."""
    if bar.low <= p.stop_loss:
        fill = min(p.stop_loss, bar.open)               # gap-down → open
        reason = "trailing" if p.trail_armed else "stop_loss"
        return reason, fill
    if bar.high >= p.take_profit:
        fill = max(p.take_profit, bar.open)             # gap-up → open
        return "take_profit", fill
    return None


def update_trail(p: Position, bar: Bar, trail_rule: str) -> Optional[ExitAdjustment]:
    """REQ-011: arm at +1R, then raise (never lower) to close − trail_dist."""
    one_r = p.entry_price - p.initial_stop
    if one_r <= 0:
        return None
    gain = bar.close - p.entry_price
    dist = _trail_distance(trail_rule)
    if not p.trail_armed:
        if gain < one_r:
            return None
        reason = "trail_armed"
    else:
        reason = "trail_raise"
    candidate = bar.close - dist if dist > 0 else p.entry_price
    new_stop = max(p.stop_loss, candidate)              # monotonic (AC-11.1)
    if new_stop <= p.stop_loss and p.trail_armed:
        return None                                      # nothing to raise
    adj = ExitAdjustment(p.session_id, p.position_id, timeuuid(),
                         bar.quote_date, p.stop_loss, new_stop, reason)
    p.stop_loss = new_stop
    p.trail_armed = True
    return adj


def close_position(p: Position, reason: str, fill: float, on,
                   repo, ledger: Ledger,
                   setup_note: Tuple[uuid.UUID, uuid.UUID]) -> ClosedTrade:
    setup_id, note_id = setup_note
    repo.add_order(Order(p.session_id, timeuuid(), setup_id, p.position_id,
                         p.ticker, "sell", "exit", fill, p.quantity, on,
                         exit_reason=reason))
    repo.remove_position(p.session_id, p.position_id)
    ledger.release(Decimal(str(p.entry_price)) * p.quantity)
    realized = (fill - p.entry_price) * p.quantity
    return ClosedTrade(
        p.session_id, p.position_id, setup_id, note_id, p.ticker,
        p.asset_class, p.quantity, p.entry_price, p.entry_date, fill, on,
        reason, round(realized, 2), (on - p.entry_date).days)


def tick(clock: MarketClock, repo, ledger: Ledger, session_id: uuid.UUID,
         setup_index: dict, log: Log) -> List[ClosedTrade]:
    """One monitoring cycle (M1–M5).
    setup_index: setup_id → (note_id, trail_rule)."""
    closed: List[ClosedTrade] = []
    today = clock.today()
    for p in repo.positions(session_id):                 # M1 one-partition read
        bar = clock.bar(p.ticker)
        if bar is None:                                  # not traded today
            p.last_check_date = today                    # cycle still counts (AC-9.1)
            repo.refresh_position(p)
            continue

        exit_hit = check_exit(p, bar)                    # M2 priority order
        if exit_hit:
            reason, fill = exit_hit
            note_id, _ = setup_index.get(p.setup_id, (None, ""))
            ct = close_position(p, reason, fill, today, repo, ledger,
                                (p.setup_id, note_id))
            closed.append(ct)
            log("MONITOR", p.ticker,
                f"CLOSED {reason} @ {fill:.2f} → realized "
                f"{ct.realized_pnl:+.2f} ({ct.holding_days}d held)")
            continue

        _, trail_rule = setup_index.get(p.setup_id, (None, ""))
        adj = update_trail(p, bar, trail_rule)
        p.current_price = bar.close                      # M3 refresh
        p.unrealized_pnl = round((bar.close - p.entry_price) * p.quantity, 2)
        p.last_check_date = today
        if adj:
            repo.raise_stop(p, adj)                      # M4
            log("MONITOR", p.ticker,
                f"trail {'armed' if adj.reason == 'trail_armed' else 'raised'}: "
                f"stop {adj.old_stop:.2f} → {adj.new_stop:.2f}")
        else:
            repo.refresh_position(p)
    return closed


def close_all(clock: MarketClock, repo, ledger: Ledger, session_id: uuid.UUID,
              setup_index: dict, reason: str, log: Log) -> List[ClosedTrade]:
    """Session end / halt / trader intervention (UF-3, REQ-010)."""
    closed = []
    for p in repo.positions(session_id):
        price = clock.latest_close(p.ticker) or p.current_price or p.entry_price
        note_id, _ = setup_index.get(p.setup_id, (None, ""))
        ct = close_position(p, reason, price, clock.today(), repo, ledger,
                            (p.setup_id, note_id))
        closed.append(ct)
        log("MONITOR", p.ticker,
            f"CLOSED {reason} @ {price:.2f} → realized {ct.realized_pnl:+.2f}")
    return closed
