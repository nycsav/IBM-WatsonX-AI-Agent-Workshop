"""Executor agent — REQ-007/008/020.

Fills approved setups at the NEXT tick's open (no same-bar hindsight,
AC-7.1), writes order + position + setup status as one logical step
(E3), and keeps the buying-power ledger invariant: committed +
remaining == starting (AC-8.1). No Presto imports (design §4.7).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Callable, List

from ..market.clock import MarketClock
from ..models import Order, Position, TradeSetup, timeuuid

Log = Callable[[str, str, str], None]


class Ledger:
    """Buying-power accounting (REQ-008)."""

    def __init__(self, starting: Decimal) -> None:
        self.starting = starting
        self.committed = Decimal("0")

    @property
    def remaining(self) -> Decimal:
        return self.starting - self.committed

    def commit(self, amount: Decimal) -> None:
        if amount > self.remaining:
            raise ValueError("insufficient buying power")
        self.committed += amount

    def release(self, amount: Decimal) -> None:
        self.committed -= amount


def run(setups: List[TradeSetup], clock: MarketClock, repo, ledger: Ledger,
        log: Log) -> List[Position]:
    """Fill every still-approved setup at today's open. Called by the
    orchestrator on the tick AFTER the Trader approved (E2)."""
    opened: List[Position] = []
    for s in [x for x in setups if x.status == "approved"]:
        bar = clock.bar(s.ticker)
        if bar is None:                      # not traded today — hold the order
            continue
        fill = Decimal(str(bar.open))        # next-bar open (AC-7.1)
        notional = fill * s.quantity
        if notional > ledger.remaining:      # actual fill exceeds power (AC-8.2)
            s.status, s.reject_reason = "rejected", "insufficient_buying_power"
            repo.mark_setup(s.session_id, s.setup_id, "rejected")
            log("EXECUTOR", s.ticker, "fill rejected: insufficient_buying_power")
            continue
        ledger.commit(notional)

        position_id = timeuuid()
        order = Order(s.session_id, timeuuid(), s.setup_id, position_id,
                      s.ticker, "buy", "entry", float(fill), s.quantity,
                      clock.today())
        pos = Position(
            s.session_id, position_id, s.setup_id, s.ticker, s.asset_class,
            s.quantity, float(fill), clock.today(), s.stop_loss, s.stop_loss,
            s.take_profit, trail_armed=False, current_price=float(fill),
            unrealized_pnl=0.0, last_check_date=clock.today())
        # E3 — one logical step
        repo.add_order(order)
        repo.add_position(pos)
        repo.mark_setup(s.session_id, s.setup_id, "executed")
        s.status = "executed"
        opened.append(pos)
        log("EXECUTOR", s.ticker,
            f"FILLED buy {s.quantity} @ {float(fill):.2f} "
            f"(notional {float(notional):.2f}, remaining power "
            f"{float(ledger.remaining):.2f})")
    return opened
