"""Domain models — one set shared by agents, repo, and API (design §6)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

ASSET_CLASSES = ("equity", "bond", "fx", "commodity", "crypto")
EXIT_REASONS = ("stop_loss", "take_profit", "trailing", "trader", "session_end")


@dataclass
class Bar:
    ticker: str
    asset_class: str
    quote_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class ResearchNote:                      # REQ-002
    session_id: uuid.UUID
    note_id: uuid.UUID
    ticker: str
    asset_class: str
    as_of_date: date
    direction: str                       # bullish | bearish | neutral
    momentum: str
    volatility: str                      # low | normal | elevated
    conviction: float                    # 0..1
    rationale: str
    shortlisted: bool = False


@dataclass
class TradeSetup:                        # REQ-004
    session_id: uuid.UUID
    setup_id: uuid.UUID
    note_id: uuid.UUID
    ticker: str
    asset_class: str
    direction: str                       # long
    entry_price: float
    quantity: int
    stop_loss: float
    take_profit: float
    trail_rule: str
    risk_amount: float
    status: str                          # proposed|approved|rejected|executed
    reject_reason: Optional[str] = None
    created_date: Optional[date] = None


@dataclass
class Position:                          # REQ-007/009/011
    session_id: uuid.UUID
    position_id: uuid.UUID
    setup_id: uuid.UUID
    ticker: str
    asset_class: str
    quantity: int
    entry_price: float
    entry_date: date
    stop_loss: float                     # CURRENT stop — monitor raises only
    initial_stop: float
    take_profit: float
    trail_armed: bool = False
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    last_check_date: Optional[date] = None


@dataclass
class Order:                             # REQ-007/008
    session_id: uuid.UUID
    order_id: uuid.UUID
    setup_id: uuid.UUID
    position_id: uuid.UUID
    ticker: str
    side: str                            # buy | sell
    order_kind: str                      # entry | exit
    fill_price: float
    quantity: int
    fill_date: date
    exit_reason: Optional[str] = None


@dataclass
class ExitAdjustment:                    # REQ-011 audit trail
    session_id: uuid.UUID
    position_id: uuid.UUID
    adj_id: uuid.UUID
    adj_date: date
    old_stop: float
    new_stop: float
    reason: str                          # trail_armed | trail_raise


@dataclass
class ClosedTrade:                       # REQ-012
    session_id: uuid.UUID
    position_id: uuid.UUID
    setup_id: uuid.UUID
    note_id: uuid.UUID
    ticker: str
    asset_class: str
    quantity: int
    entry_price: float
    entry_date: date
    exit_price: float
    exit_date: date
    exit_reason: str
    realized_pnl: float
    holding_days: int


def timeuuid() -> uuid.UUID:
    return uuid.uuid1()
