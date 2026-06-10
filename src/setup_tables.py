"""Idempotent DDL — design §3. Safe to re-run (REQ-017/AC-1).

Writes only to user-31's slices (REQ-018): keyspace financial_userNN
and iceberg_data.financial_userNN.
"""
from __future__ import annotations

import asyncio

from .config import settings
from .db import cassandra
from .db.presto import PrestoClient

CASSANDRA_DDL = [
    """CREATE TABLE IF NOT EXISTS research_notes (
        session_id TIMEUUID, note_id TIMEUUID, ticker TEXT, asset_class TEXT,
        as_of_date DATE, direction TEXT, momentum TEXT, volatility TEXT,
        conviction DOUBLE, rationale TEXT, shortlisted BOOLEAN,
        news_context TEXT,
        PRIMARY KEY ((session_id), note_id)
    ) WITH CLUSTERING ORDER BY (note_id DESC)""",
    """CREATE TABLE IF NOT EXISTS trade_setups (
        session_id TIMEUUID, setup_id TIMEUUID, note_id TIMEUUID, ticker TEXT,
        asset_class TEXT, direction TEXT, entry_price DOUBLE, quantity INT,
        stop_loss DOUBLE, take_profit DOUBLE, trail_rule TEXT,
        risk_amount DOUBLE, status TEXT, reject_reason TEXT, created_date DATE,
        PRIMARY KEY ((session_id), setup_id)
    ) WITH CLUSTERING ORDER BY (setup_id DESC)""",
    """CREATE TABLE IF NOT EXISTS positions_open (
        session_id TIMEUUID, position_id TIMEUUID, setup_id TIMEUUID,
        ticker TEXT, asset_class TEXT, quantity INT, entry_price DOUBLE,
        entry_date DATE, stop_loss DOUBLE, initial_stop DOUBLE,
        take_profit DOUBLE, trail_armed BOOLEAN, current_price DOUBLE,
        unrealized_pnl DOUBLE, last_check_date DATE,
        PRIMARY KEY ((session_id), position_id)
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        session_id TIMEUUID, order_id TIMEUUID, setup_id TIMEUUID,
        position_id TIMEUUID, ticker TEXT, side TEXT, order_kind TEXT,
        fill_price DOUBLE, quantity INT, fill_date DATE, exit_reason TEXT,
        PRIMARY KEY ((session_id), order_id)
    ) WITH CLUSTERING ORDER BY (order_id DESC)""",
    """CREATE TABLE IF NOT EXISTS exit_adjustments (
        session_id TIMEUUID, position_id TIMEUUID, adj_id TIMEUUID,
        adj_date DATE, old_stop DOUBLE, new_stop DOUBLE, reason TEXT,
        PRIMARY KEY ((session_id, position_id), adj_id)
    ) WITH CLUSTERING ORDER BY (adj_id ASC)""",
]

ICEBERG_DDL = """CREATE TABLE IF NOT EXISTS {schema}.trades_closed (
    session_id VARCHAR, position_id VARCHAR, setup_id VARCHAR,
    note_id VARCHAR, ticker VARCHAR, asset_class VARCHAR, quantity INTEGER,
    entry_price DECIMAL(14,4), entry_date DATE, exit_price DECIMAL(14,4),
    exit_date DATE, exit_reason VARCHAR, realized_pnl DECIMAL(14,2),
    holding_days INTEGER, exit_year INTEGER, exit_month INTEGER
) WITH (format = 'PARQUET', partitioning = ARRAY['exit_year','exit_month'])"""


def create_cassandra_tables() -> None:
    s = cassandra.connect()
    for ddl in CASSANDRA_DDL:
        s.execute(ddl)
    try:                       # migration for tables created pre-enrichment
        s.execute("ALTER TABLE research_notes ADD news_context TEXT")
    except Exception:
        pass                   # column already exists
    print(f"[OK] Cassandra tables ready in {settings.keyspace}")


async def create_iceberg_tables(presto: PrestoClient) -> None:
    await presto.query(ICEBERG_DDL.format(schema=settings.iceberg_schema))
    print(f"[OK] Iceberg table ready: {settings.iceberg_schema}.trades_closed")


async def main() -> None:
    create_cassandra_tables()
    presto = PrestoClient()
    try:
        await create_iceberg_tables(presto)
    finally:
        await presto.close()


if __name__ == "__main__":
    asyncio.run(main())
