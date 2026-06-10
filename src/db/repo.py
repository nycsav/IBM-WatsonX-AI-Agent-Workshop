"""Hot-state repository interface + in-memory test double.

Agents depend on this interface only. The live implementation
(CassandraRepo) issues single-partition CQL; the InMemoryRepo backs the
unit tests (test-plan levels U) so they never need the cluster.
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from ..models import (ClosedTrade, ExitAdjustment, Order, Position,
                      ResearchNote, TradeSetup)


class Repo:
    """Interface — every read is 'everything for this session' (one partition)."""

    # research_notes
    def add_note(self, n: ResearchNote) -> None: raise NotImplementedError
    def notes(self, session_id: uuid.UUID) -> List[ResearchNote]: raise NotImplementedError

    # trade_setups
    def add_setup(self, s: TradeSetup) -> None: raise NotImplementedError
    def setups(self, session_id: uuid.UUID) -> List[TradeSetup]: raise NotImplementedError
    def mark_setup(self, session_id: uuid.UUID, setup_id: uuid.UUID, status: str) -> None:
        raise NotImplementedError

    # positions_open
    def add_position(self, p: Position) -> None: raise NotImplementedError
    def positions(self, session_id: uuid.UUID) -> List[Position]: raise NotImplementedError
    def refresh_position(self, p: Position) -> None: raise NotImplementedError
    def raise_stop(self, p: Position, adj: ExitAdjustment) -> None: raise NotImplementedError
    def remove_position(self, session_id: uuid.UUID, position_id: uuid.UUID) -> None:
        raise NotImplementedError

    # orders
    def add_order(self, o: Order) -> None: raise NotImplementedError
    def orders(self, session_id: uuid.UUID, limit: Optional[int] = None) -> List[Order]:
        raise NotImplementedError

    # exit_adjustments
    def adjustments(self, session_id: uuid.UUID,
                    position_id: uuid.UUID) -> List[ExitAdjustment]:
        raise NotImplementedError


class InMemoryRepo(Repo):
    """Test double — same contract, plain dicts."""

    def __init__(self) -> None:
        self._notes: List[ResearchNote] = []
        self._setups: List[TradeSetup] = []
        self._positions: Dict[uuid.UUID, Position] = {}
        self._orders: List[Order] = []
        self._adjs: List[ExitAdjustment] = []

    def add_note(self, n): self._notes.append(n)
    def notes(self, sid): return [n for n in self._notes if n.session_id == sid]

    def add_setup(self, s): self._setups.append(s)
    def setups(self, sid): return [s for s in self._setups if s.session_id == sid]

    def mark_setup(self, sid, setup_id, status):
        for s in self._setups:
            if s.session_id == sid and s.setup_id == setup_id:
                s.status = status

    def add_position(self, p): self._positions[p.position_id] = p
    def positions(self, sid):
        return [p for p in self._positions.values() if p.session_id == sid]

    def refresh_position(self, p): self._positions[p.position_id] = p

    def raise_stop(self, p, adj):
        self._positions[p.position_id] = p
        self._adjs.append(adj)

    def remove_position(self, sid, pid): self._positions.pop(pid, None)

    def add_order(self, o): self._orders.append(o)
    def orders(self, sid, limit=None):
        out = [o for o in self._orders if o.session_id == sid]
        out.sort(key=lambda o: o.order_id.time, reverse=True)
        return out[:limit] if limit else out

    def adjustments(self, sid, pid):
        return [a for a in self._adjs
                if a.session_id == sid and a.position_id == pid]
