"""Cassandra hot-state client — TLS route :443, endpoint-factory pin.

Connection mechanics mirror setup/lib/smoke_test.py exactly (AGENTS.md
detail #4). Routing invariant (design §4.7): this module exposes ONLY
partition-keyed prepared statements — every SELECT names the partition
key in its WHERE clause; no scans, no ALLOW FILTERING.
"""
from __future__ import annotations

import ssl
import uuid
from typing import List, Optional

from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster, Session
from cassandra.connection import DefaultEndPoint, EndPointFactory
from cassandra.query import BatchStatement

from ..config import settings
from ..models import (ExitAdjustment, Order, Position, ResearchNote,
                      TradeSetup)
from .repo import Repo


class _RouteEndPointFactory(EndPointFactory):
    """Collapse every discovered node to the one reachable Route endpoint
    (host:443). Without this the driver dials internal 10.x pod IPs on
    9042 and stalls a full connect-timeout per node."""

    def __init__(self, host: str, port: int) -> None:
        self._host, self._port = host, port

    def create(self, row):
        return DefaultEndPoint(self._host, self._port)

    def create_from_sni(self, sni):
        return DefaultEndPoint(self._host, self._port)


_cluster: Optional[Cluster] = None
_session: Optional[Session] = None


def connect() -> Session:
    """One session per process, bound to the attendee keyspace."""
    global _cluster, _session
    if _session is not None:
        return _session
    ctx = ssl.create_default_context()
    ctx.check_hostname = False          # cert SANs are hostnames, driver dials IP
    _cluster = Cluster(
        contact_points=[settings.cassandra_host],
        port=settings.cassandra_port,
        ssl_context=ctx,
        ssl_options={"server_hostname": settings.cassandra_host},   # SNI
        auth_provider=PlainTextAuthProvider(settings.user, settings.password),
        endpoint_factory=_RouteEndPointFactory(settings.cassandra_host,
                                               settings.cassandra_port),
        connect_timeout=15,
    )
    _session = _cluster.connect(settings.keyspace)
    return _session


def shutdown() -> None:
    global _cluster, _session
    if _cluster is not None:
        _cluster.shutdown()
    _cluster = _session = None


# --- statement registry -----------------------------------------------------
# Audited by TST-RT2: every SELECT/UPDATE/DELETE keys on session_id (the
# partition key); INSERTs are full-row. Nothing else may be added here
# without keeping that property.
_STMTS = {
    "note_ins": ("INSERT INTO research_notes (session_id, note_id, ticker,"
                 " asset_class, as_of_date, direction, momentum, volatility,"
                 " conviction, rationale, shortlisted)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?,?)"),
    "note_sel": "SELECT * FROM research_notes WHERE session_id = ?",
    "setup_ins": ("INSERT INTO trade_setups (session_id, setup_id, note_id,"
                  " ticker, asset_class, direction, entry_price, quantity,"
                  " stop_loss, take_profit, trail_rule, risk_amount, status,"
                  " reject_reason, created_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"),
    "setup_sel": "SELECT * FROM trade_setups WHERE session_id = ?",
    "setup_upd": ("UPDATE trade_setups SET status = ?"
                  " WHERE session_id = ? AND setup_id = ?"),
    "pos_ins": ("INSERT INTO positions_open (session_id, position_id, setup_id,"
                " ticker, asset_class, quantity, entry_price, entry_date,"
                " stop_loss, initial_stop, take_profit, trail_armed,"
                " current_price, unrealized_pnl, last_check_date)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"),
    "pos_sel": "SELECT * FROM positions_open WHERE session_id = ?",
    "pos_mark": ("UPDATE positions_open SET current_price = ?, unrealized_pnl = ?,"
                 " last_check_date = ? WHERE session_id = ? AND position_id = ?"),
    "pos_stop": ("UPDATE positions_open SET stop_loss = ?, trail_armed = true"
                 " WHERE session_id = ? AND position_id = ?"),
    "pos_del": "DELETE FROM positions_open WHERE session_id = ? AND position_id = ?",
    "order_ins": ("INSERT INTO orders (session_id, order_id, setup_id, position_id,"
                  " ticker, side, order_kind, fill_price, quantity, fill_date,"
                  " exit_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)"),
    "order_sel": "SELECT * FROM orders WHERE session_id = ?",
    "adj_ins": ("INSERT INTO exit_adjustments (session_id, position_id, adj_id,"
                " adj_date, old_stop, new_stop, reason) VALUES (?,?,?,?,?,?,?)"),
    "adj_sel": ("SELECT * FROM exit_adjustments"
                " WHERE session_id = ? AND position_id = ?"),
}


class CassandraRepo(Repo):
    """Live implementation of the hot-state repo (design §4 [C] patterns)."""

    def __init__(self) -> None:
        self.s = connect()
        self.p = {k: self.s.prepare(q) for k, q in _STMTS.items()}

    # research_notes
    def add_note(self, n: ResearchNote) -> None:
        self.s.execute(self.p["note_ins"], (
            n.session_id, n.note_id, n.ticker, n.asset_class, n.as_of_date,
            n.direction, n.momentum, n.volatility, n.conviction, n.rationale,
            n.shortlisted))

    def notes(self, sid: uuid.UUID) -> List[ResearchNote]:
        return [ResearchNote(r.session_id, r.note_id, r.ticker, r.asset_class,
                             r.as_of_date.date(), r.direction, r.momentum,
                             r.volatility, float(r.conviction), r.rationale,
                             r.shortlisted)
                for r in self.s.execute(self.p["note_sel"], (sid,))]

    # trade_setups
    def add_setup(self, t: TradeSetup) -> None:
        self.s.execute(self.p["setup_ins"], (
            t.session_id, t.setup_id, t.note_id, t.ticker, t.asset_class,
            t.direction, t.entry_price, t.quantity, t.stop_loss, t.take_profit,
            t.trail_rule, t.risk_amount, t.status, t.reject_reason,
            t.created_date))

    def setups(self, sid: uuid.UUID) -> List[TradeSetup]:
        return [TradeSetup(r.session_id, r.setup_id, r.note_id, r.ticker,
                           r.asset_class, r.direction, float(r.entry_price),
                           r.quantity, float(r.stop_loss), float(r.take_profit),
                           r.trail_rule, float(r.risk_amount), r.status,
                           r.reject_reason, r.created_date.date())
                for r in self.s.execute(self.p["setup_sel"], (sid,))]

    def mark_setup(self, sid, setup_id, status) -> None:
        self.s.execute(self.p["setup_upd"], (status, sid, setup_id))

    # positions_open
    def add_position(self, p: Position) -> None:
        self.s.execute(self.p["pos_ins"], (
            p.session_id, p.position_id, p.setup_id, p.ticker, p.asset_class,
            p.quantity, p.entry_price, p.entry_date, p.stop_loss,
            p.initial_stop, p.take_profit, p.trail_armed, p.current_price,
            p.unrealized_pnl, p.last_check_date))

    def positions(self, sid: uuid.UUID) -> List[Position]:
        return [Position(r.session_id, r.position_id, r.setup_id, r.ticker,
                         r.asset_class, r.quantity, float(r.entry_price),
                         r.entry_date.date(), float(r.stop_loss),
                         float(r.initial_stop), float(r.take_profit),
                         r.trail_armed, float(r.current_price),
                         float(r.unrealized_pnl),
                         r.last_check_date.date() if r.last_check_date else None)
                for r in self.s.execute(self.p["pos_sel"], (sid,))]

    def refresh_position(self, p: Position) -> None:
        self.s.execute(self.p["pos_mark"], (
            p.current_price, p.unrealized_pnl, p.last_check_date,
            p.session_id, p.position_id))

    def raise_stop(self, p: Position, adj: ExitAdjustment) -> None:
        self.s.execute(self.p["pos_stop"], (p.stop_loss, p.session_id, p.position_id))
        self.s.execute(self.p["adj_ins"], (
            adj.session_id, adj.position_id, adj.adj_id, adj.adj_date,
            adj.old_stop, adj.new_stop, adj.reason))

    def remove_position(self, sid, pid) -> None:
        self.s.execute(self.p["pos_del"], (sid, pid))

    # orders
    def add_order(self, o: Order) -> None:
        self.s.execute(self.p["order_ins"], (
            o.session_id, o.order_id, o.setup_id, o.position_id, o.ticker,
            o.side, o.order_kind, o.fill_price, o.quantity, o.fill_date,
            o.exit_reason))

    def orders(self, sid: uuid.UUID, limit: Optional[int] = None) -> List[Order]:
        rows = [Order(r.session_id, r.order_id, r.setup_id, r.position_id,
                      r.ticker, r.side, r.order_kind, float(r.fill_price),
                      r.quantity, r.fill_date.date(), r.exit_reason)
                for r in self.s.execute(self.p["order_sel"], (sid,))]
        return rows[:limit] if limit else rows

    # exit_adjustments
    def adjustments(self, sid, pid) -> List[ExitAdjustment]:
        return [ExitAdjustment(r.session_id, r.position_id, r.adj_id,
                               r.adj_date.date(), float(r.old_stop),
                               float(r.new_stop), r.reason)
                for r in self.s.execute(self.p["adj_sel"], (sid, pid))]
