"""Orchestrator — session lifecycle (design §1, REQ-013/014/015/020).

One asyncio process: bootstrap (B1/B2), one bulk market load (B4), then
the unattended loop: research → setups → fills → monitor ticks, with
closed trades flushed to Iceberg off the tick path (M5) and a final
reconciled summary (REQ-015). Zero prompts anywhere (REQ-020).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from .agents import executor, monitor, researcher, trader
from .agents.executor import Ledger
from .config import settings
from .db.cassandra import CassandraRepo
from .db.presto import PrestoClient
from .market.clock import MarketClock, load_clock
from .models import ClosedTrade

console = Console()

RE_RESEARCH_EVERY = 10          # ticks between fresh research passes


class Session:
    def __init__(self) -> None:
        self.session_id = uuid.uuid1()
        self.state = "starting"
        self.repo: Optional[CassandraRepo] = None
        self.presto = PrestoClient()
        self.clock: Optional[MarketClock] = None
        self.ledger: Optional[Ledger] = None
        self.account_id: Optional[str] = None
        self.customer_id: Optional[str] = None
        self.setup_index: Dict[uuid.UUID, Tuple[uuid.UUID, str]] = {}
        self.pending_setups: List = []
        self.closed: List[ClosedTrade] = []
        self.flush_buffer: List[ClosedTrade] = []
        self.log_lines: List[Tuple[str, str, str, str]] = []
        self.equity_curve: List[float] = []
        self.accept_new = True               # cleared by halt(keep_positions=True)
        self.started_at = dt.datetime.now()

    # --- decision log (REQ-014) ----------------------------------------------
    def log(self, agent: str, ticker: str, msg: str) -> None:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        sim = str(self.clock.today()) if self.clock else "-"
        self.log_lines.append((ts, sim, agent, f"{ticker}: {msg}"))
        color = {"RESEARCH": "cyan", "TRADER": "yellow", "EXECUTOR": "green",
                 "MONITOR": "magenta", "SESSION": "white"}.get(agent, "white")
        console.print(f"[dim]{ts} d={sim}[/dim] [{color}]{agent:8}[/{color}] "
                      f"{ticker:8} {msg}")

    # --- bootstrap ------------------------------------------------------------
    async def bootstrap(self) -> None:
        self.log("SESSION", "*", f"session {self.session_id} starting "
                 f"as {settings.user}")
        # B1 — analytical account pick via Presto over the cassandra catalog:
        # richest active investment account whose OWNER passes the REQ-006
        # risk-profile gate (join accounts ⋈ customers, global sort).
        _, rows = await self.presto.query(
            f"SELECT a.account_id, a.customer_id, a.available_balance"
            f" FROM {settings.federated_keyspace}.accounts a"
            f" JOIN {settings.federated_keyspace}.customers c"
            f"   ON c.customer_id = a.customer_id"
            f" WHERE a.account_type = 'investment' AND a.status = 'active'"
            f"   AND lower(c.risk_tier) NOT IN ('high', 'restricted')"
            f"   AND c.account_status = 'active'"
            f" ORDER BY a.available_balance DESC LIMIT 1")
        if not rows:
            raise RuntimeError("no eligible active investment account found")
        self.account_id, self.customer_id, balance = rows[0]
        balance = Decimal(str(balance))
        self.repo = CassandraRepo()
        # B2 — risk-profile gate (REQ-006), hot PK lookup
        row = self.repo.s.execute(
            "SELECT risk_tier, account_status FROM customers"
            " WHERE customer_id = %s", (uuid.UUID(self.customer_id),)).one()
        tier = row.risk_tier if row else "unknown"
        if not trader.risk_tier_allowed(tier):
            raise RuntimeError(f"risk tier '{tier}' is blocked — not trading")
        self.ledger = Ledger(balance)
        self.log("SESSION", "*",
                 f"account {self.account_id[:8]}… balance {balance:,.2f}, "
                 f"risk tier {tier} → trading allowed")
        # B4 — the one bulk market load
        self.clock = await load_clock(self.presto, settings.reference_schema,
                                      settings.lookback_days)
        self.log("SESSION", "*",
                 f"market loaded: {len(self.clock.tickers())} instruments, "
                 f"classes {self.clock.asset_classes()}, "
                 f"replay {len(self.clock._dates) - settings.lookback_days} days "
                 f"from {self.clock.today()}")

    # --- agent passes -----------------------------------------------------------
    def research_and_setup(self) -> None:
        notes = researcher.run(self.clock, self.repo, self.session_id,
                               settings.shortlist_size, self.log)
        positions = self.repo.positions(self.session_id)
        setups = trader.run(notes, positions, self.ledger.starting,
                            self.clock, self.repo, settings, self.log)
        for s in setups:
            self.setup_index[s.setup_id] = (s.note_id, s.trail_rule)
        self.pending_setups.extend(s for s in setups if s.status == "approved")

    def fill_pending(self) -> None:
        if not self.pending_setups:
            return
        executor.run(self.pending_setups, self.clock, self.repo,
                     self.ledger, self.log)
        self.pending_setups = [s for s in self.pending_setups
                               if s.status == "approved"]   # unfilled hold over

    async def flush_closed(self) -> None:
        """M5 off-tick-path Iceberg archival (REQ-012); retried next flush."""
        if not self.flush_buffer:
            return
        batch, self.flush_buffer = self.flush_buffer, []
        values = ", ".join(
            f"('{c.session_id}','{c.position_id}','{c.setup_id}',"
            f"'{c.note_id}','{c.ticker}','{c.asset_class}',{c.quantity},"
            f"{c.entry_price},DATE '{c.entry_date}',{c.exit_price},"
            f"DATE '{c.exit_date}','{c.exit_reason}',{c.realized_pnl},"
            f"{c.holding_days},{c.exit_date.year},{c.exit_date.month})"
            for c in batch)
        try:
            await self.presto.query(
                f"INSERT INTO {settings.iceberg_schema}.trades_closed"
                f" (session_id, position_id, setup_id, note_id, ticker,"
                f" asset_class, quantity, entry_price, entry_date, exit_price,"
                f" exit_date, exit_reason, realized_pnl, holding_days,"
                f" exit_year, exit_month) VALUES {values}")
        except Exception as e:                       # retry on next flush
            self.flush_buffer.extend(batch)
            self.log("SESSION", "*", f"archive flush deferred: {e}")

    # --- P/L (REQ-021) -----------------------------------------------------------
    def realized_pnl(self) -> float:
        return round(sum(c.realized_pnl for c in self.closed), 2)

    def unrealized_pnl(self) -> float:
        return round(sum(p.unrealized_pnl
                         for p in self.repo.positions(self.session_id)), 2)

    # --- snapshot (REQ-022) — hot reads only ---------------------------------------
    def snapshot(self) -> None:
        t = Table(title=f"TradeCrew snapshot — sim {self.clock.today()} "
                        f"(session {str(self.session_id)[:8]}…)")
        for col in ("ticker", "qty", "entry", "now", "uP/L", "stop", "target",
                    "trail"):
            t.add_column(col, justify="right")
        for p in self.repo.positions(self.session_id):
            t.add_row(p.ticker, str(p.quantity), f"{p.entry_price:.2f}",
                      f"{p.current_price:.2f}", f"{p.unrealized_pnl:+.2f}",
                      f"{p.stop_loss:.2f}", f"{p.take_profit:.2f}",
                      "armed" if p.trail_armed else "—")
        console.print(t)
        console.print(
            f"  realized {self.realized_pnl():+,.2f} · "
            f"unrealized {self.unrealized_pnl():+,.2f} · "
            f"buying power {float(self.ledger.remaining):,.2f}")
        for ts, sim, agent, msg in self.log_lines[-5:]:
            console.print(f"  [dim]{ts} {agent}[/dim] {msg}")

    # --- summary (REQ-015) ----------------------------------------------------------
    def summary(self) -> dict:
        wins = [c for c in self.closed if c.realized_pnl > 0]
        eq = self.equity_curve or [0.0]
        peak, max_dd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            max_dd = min(max_dd, v - peak)
        out = {
            "session_id": str(self.session_id),
            "trades_opened": len(self.closed) + len(
                self.repo.positions(self.session_id)),
            "trades_closed": len(self.closed),
            "win_rate": round(len(wins) / len(self.closed), 3) if self.closed else 0.0,
            "realized_pnl": self.realized_pnl(),
            "unrealized_pnl": self.unrealized_pnl(),
            "max_drawdown": round(max_dd, 2),
            "by_exit_reason": {},
        }
        for c in self.closed:
            out["by_exit_reason"][c.exit_reason] = \
                out["by_exit_reason"].get(c.exit_reason, 0) + 1
        return out

    # --- interventions (UF-3) -------------------------------------------------------
    def close_one(self, position_id: str) -> Optional[ClosedTrade]:
        """Trader-initiated exit at current market price (REQ-010 'trader')."""
        for p in self.repo.positions(self.session_id):
            if str(p.position_id) == str(position_id):
                note_id, _ = self.setup_index.get(p.setup_id, (None, ""))
                price = (self.clock.latest_close(p.ticker)
                         or p.current_price or p.entry_price)
                ct = monitor.close_position(
                    p, "trader", price, self.clock.today(), self.repo,
                    self.ledger, (p.setup_id, note_id))
                self.closed.append(ct)
                self.flush_buffer.append(ct)
                self.log("MONITOR", p.ticker,
                         f"CLOSED trader @ {price:.2f} → realized "
                         f"{ct.realized_pnl:+.2f} (operator intervention)")
                return ct
        return None

    def halt(self, keep_positions: bool = False) -> bool:
        """UF-3 halt: stop opening new positions. keep_positions=True lets
        the Monitor manage the existing book to plan; otherwise close all
        now at market (reason 'trader')."""
        if self.state != "running":
            return False
        self.accept_new = False
        if not keep_positions:
            for p in list(self.repo.positions(self.session_id)):
                self.close_one(str(p.position_id))
            self.state = "halted"
        self.log("SESSION", "*",
                 f"HALT requested (keep_positions={keep_positions})")
        return True

    # --- the federated centerpiece (REQ-016) -------------------------------------------
    async def unified_pnl(self) -> List[list]:
        sql = f"""WITH latest AS (
  SELECT ticker, max(quote_date) AS d
  FROM {settings.reference_schema}.market_data_daily
  WHERE quote_date <= DATE '{self.clock.today()}'
  GROUP BY ticker)
SELECT p.ticker, 'OPEN' AS state, p.quantity, p.entry_price,
       m.close_price AS mark,
       (m.close_price - p.entry_price) * p.quantity AS pnl
FROM {settings.federated_keyspace}.positions_open p
JOIN latest l ON l.ticker = p.ticker
JOIN {settings.reference_schema}.market_data_daily m
  ON m.ticker = l.ticker AND m.quote_date = l.d
WHERE p.session_id = '{self.session_id}'
UNION ALL
SELECT t.ticker, 'CLOSED', t.quantity, CAST(t.entry_price AS DOUBLE),
       CAST(t.exit_price AS DOUBLE), CAST(t.realized_pnl AS DOUBLE)
FROM {settings.iceberg_schema}.trades_closed t
WHERE t.session_id = '{self.session_id}'
ORDER BY state, pnl DESC"""
        _, rows = await self.presto.query(sql)
        return rows

    # --- main loop (REQ-020: unattended) --------------------------------------------------
    async def run(self, max_ticks: Optional[int] = None,
                  tick_seconds: Optional[float] = None,
                  close_at_end: bool = True) -> dict:
        pace = tick_seconds if tick_seconds is not None else settings.tick_seconds
        await self.bootstrap()
        self.state = "running"
        self.research_and_setup()

        ticks = 0
        snapshot_at = (max_ticks or
                       (len(self.clock._dates) - settings.lookback_days)) // 2
        while not self.clock.exhausted and self.state == "running":
            if max_ticks is not None and ticks >= max_ticks:
                break
            await asyncio.sleep(pace)
            self.clock.advance()
            ticks += 1
            if self.accept_new:
                self.fill_pending()                          # E2 next-bar fills
            newly = monitor.tick(self.clock, self.repo, self.ledger,
                                 self.session_id, self.setup_index, self.log)
            self.closed.extend(newly)
            self.flush_buffer.extend(newly)
            self.equity_curve.append(self.realized_pnl() + self.unrealized_pnl())
            if newly:
                asyncio.create_task(self.flush_closed())     # off tick path
            if ticks == snapshot_at:                         # UF-2 check-in demo
                self.snapshot()
            if ticks % RE_RESEARCH_EVERY == 0 and self.accept_new:
                self.research_and_setup()

        if close_at_end:
            # session end: close what's open (REQ-010 session_end)
            end_closed = monitor.close_all(self.clock, self.repo, self.ledger,
                                           self.session_id, self.setup_index,
                                           "session_end", self.log)
            self.closed.extend(end_closed)
            self.flush_buffer.extend(end_closed)
        await self.flush_closed()
        self.state = "ended"

        s = self.summary()
        console.rule("[bold]Session summary (REQ-015)")
        console.print(
            f"  trades closed {s['trades_closed']} · win rate "
            f"{s['win_rate']:.0%} · realized {s['realized_pnl']:+,.2f} · "
            f"unrealized {s['unrealized_pnl']:+,.2f} · max drawdown "
            f"{s['max_drawdown']:,.2f}")
        console.print(f"  exits: {s['by_exit_reason']}")
        try:
            rows = await self.unified_pnl()
            console.rule("[bold]Federated hot+cold P/L (REQ-016, one statement)")
            for r in rows:
                console.print(f"  {r[0]:>8} {r[1]:>6} qty {r[2]:>5} "
                              f"entry {r[3]:>10.2f} mark/exit {r[4]:>10.2f} "
                              f"P/L {r[5]:>+10.2f}")
        except Exception as e:
            console.print(f"  federated view unavailable: {e}")
        await self.presto.close()
        return s
