"""Trader agent — REQ-004..006, REQ-019.

Turns shortlisted notes into complete setups (entry/size/stop/target/
trail rule) and enforces every guardrail, recording the specific
guardrail on rejection (AC-6.1). Sizing math in Decimal (AC-5.1).
Single-writer gate: called sequentially by the orchestrator so the
risk/ledger invariants can't race. No Presto imports (design §4.7).
"""
from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal
from typing import Callable, List

from ..config import Settings
from ..market import indicators as ind
from ..market.clock import MarketClock
from ..models import Position, ResearchNote, TradeSetup, timeuuid

Log = Callable[[str, str, str], None]

BLOCKED_TIERS = {"high", "restricted"}           # REQ-006 risk profile gate


def risk_tier_allowed(tier: str) -> bool:
    return (tier or "").lower() not in BLOCKED_TIERS


def open_risk(positions: List[Position]) -> Decimal:
    """Aggregate open risk = Σ (entry − current stop) × qty, floored at 0."""
    total = Decimal("0")
    for p in positions:
        per_share = Decimal(str(p.entry_price)) - Decimal(str(p.stop_loss))
        if per_share > 0:
            total += per_share * p.quantity
    return total


def committed_capital(positions: List[Position]) -> Decimal:
    return sum((Decimal(str(p.entry_price)) * p.quantity for p in positions),
               Decimal("0"))


def build_setup(note: ResearchNote, clock: MarketClock,
                cfg: Settings) -> TradeSetup:
    """Entry at last close; stop = entry − 2×ATR(14) (5% fallback);
    target ≥ 2:1 reward:risk (AC-4.2); trail arms at +1R, 1.5×ATR wide."""
    bars = clock.history(note.ticker, 90)
    entry = Decimal(str(bars[-1].close))
    a = ind.atr(bars, 14)
    stop_dist = (Decimal(str(a)) * 2) if a else entry * Decimal("0.05")
    stop = entry - stop_dist
    target = entry + stop_dist * 2                      # exactly 2:1
    trail_dist = (Decimal(str(a)) * Decimal("1.5")) if a \
        else entry * Decimal("0.0375")
    return TradeSetup(
        session_id=note.session_id, setup_id=timeuuid(), note_id=note.note_id,
        ticker=note.ticker, asset_class=note.asset_class, direction="long",
        entry_price=float(entry), quantity=0,           # sized below
        stop_loss=float(stop), take_profit=float(target),
        trail_rule=f"arm@+1R;trail=1.5xATR={float(trail_dist):.4f}",
        risk_amount=0.0, status="proposed", created_date=clock.today())


def size_and_check(setup: TradeSetup, positions: List[Position],
                   balance: Decimal, cfg: Settings) -> TradeSetup:
    """Apply REQ-005 sizing then the REQ-006/008/019 guardrails in a fixed
    order. Mutates setup to approved (with quantity) or rejected (with
    reason). Order: concurrency → sizing → buying power → aggregate risk
    → class cap."""
    if len(positions) >= cfg.max_open_positions:
        setup.status, setup.reject_reason = "rejected", "max_open_positions"
        return setup

    entry = Decimal(str(setup.entry_price))
    stop = Decimal(str(setup.stop_loss))
    per_share_risk = entry - stop
    risk_budget = balance * Decimal(str(cfg.risk_per_trade_pct)) / 100

    qty = int((risk_budget / per_share_risk).to_integral_value(ROUND_DOWN))
    if qty < 1:                                          # AC-5.2: reject, don't shrink
        setup.status, setup.reject_reason = "rejected", "risk_budget"
        return setup
    risk_amount = per_share_risk * qty

    remaining = balance - committed_capital(positions)
    if entry * qty > remaining:
        # shrink to what buying power allows, but never below viability
        qty_bp = int((remaining / entry).to_integral_value(ROUND_DOWN))
        if qty_bp < 1:
            setup.status, setup.reject_reason = ("rejected",
                                                 "insufficient_buying_power")
            return setup
        qty = min(qty, qty_bp)
        risk_amount = per_share_risk * qty

    agg_cap = balance * Decimal(str(cfg.max_aggregate_risk_pct)) / 100
    current_risk = open_risk(positions)
    if current_risk + risk_amount > agg_cap:
        setup.status, setup.reject_reason = "rejected", "aggregate_risk"
        return setup

    # REQ-019: this class's share of post-trade aggregate open risk
    class_risk = open_risk([p for p in positions
                            if p.asset_class == setup.asset_class])
    post_total = current_risk + risk_amount
    cap_pct = Decimal(str(cfg.class_cap(setup.asset_class))) / 100
    if post_total > 0 and (class_risk + risk_amount) / post_total > cap_pct \
            and current_risk > 0:        # cap binds only once a book exists
        setup.status, setup.reject_reason = "rejected", "class_risk_cap"
        return setup

    setup.quantity = qty
    setup.risk_amount = float(risk_amount)
    setup.status = "approved"
    return setup


def run(notes: List[ResearchNote], positions: List[Position],
        balance: Decimal, clock: MarketClock, repo, cfg: Settings,
        log: Log) -> List[TradeSetup]:
    """Process the shortlist sequentially (single-writer gate)."""
    out: List[TradeSetup] = []
    working = list(positions)
    for note in [n for n in notes if n.shortlisted]:
        if any(p.ticker == note.ticker for p in working):
            continue                                    # already in the book
        setup = size_and_check(build_setup(note, clock, cfg), working,
                               balance, cfg)
        repo.add_setup(setup)
        out.append(setup)
        if setup.status == "approved":
            # reserve against subsequent setups in this same pass
            working.append(Position(
                setup.session_id, uuid.uuid4(), setup.setup_id, setup.ticker,
                setup.asset_class, setup.quantity, setup.entry_price,
                clock.today(), setup.stop_loss, setup.stop_loss,
                setup.take_profit))
            log("TRADER", setup.ticker,
                f"setup approved: {setup.quantity} @ ~{setup.entry_price:.2f}, "
                f"stop {setup.stop_loss:.2f}, target {setup.take_profit:.2f}, "
                f"risk {setup.risk_amount:.2f}")
        else:
            log("TRADER", setup.ticker,
                f"setup rejected: {setup.reject_reason}")
    return out
