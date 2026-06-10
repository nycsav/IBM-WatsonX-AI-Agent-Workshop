"""One-time external crypto feed → our own Iceberg slice (REQ-018 safe).

Fetches real daily OHLCV from Coinbase Exchange's PUBLIC candles API
(no key) for BTC/ETH/SOL, clamped to the workshop reference-data date
window, and lands it in iceberg_data.financial_userNN.market_data_daily_ext.
The market clock unions this with the shared reference feed — giving the
'crypto' asset class real data so REQ-019 diversification (and the 30%
crypto risk cap) actually binds.

Run once:  .venv/bin/python -m src.load_crypto   (idempotent)
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import List

import httpx

from .config import settings
from .db.presto import PrestoClient

PRODUCTS = {"BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL"}
API = "https://api.exchange.coinbase.com/products/{product}/candles"

EXT_DDL = """CREATE TABLE IF NOT EXISTS {schema}.market_data_daily_ext (
    ticker VARCHAR, asset_class VARCHAR, quote_date DATE,
    quote_year INTEGER, open_price DECIMAL(14,4), high_price DECIMAL(14,4),
    low_price DECIMAL(14,4), close_price DECIMAL(14,4), volume BIGINT,
    currency VARCHAR, source VARCHAR
) WITH (format = 'PARQUET', partitioning = ARRAY['quote_year'])"""


async def fetch_candles(http: httpx.AsyncClient, product: str,
                        start: dt.date, end: dt.date) -> List[list]:
    """Daily candles [time, low, high, open, close, volume], paged ≤300."""
    r = await http.get(API.format(product=product),
                       params={"granularity": 86400,
                               "start": f"{start}T00:00:00Z",
                               "end": f"{end}T23:59:59Z"})
    r.raise_for_status()
    return r.json()


async def main() -> None:
    presto = PrestoClient()
    http = httpx.AsyncClient(timeout=30.0)
    try:
        # Clamp to the shared reference window so the clock's replay
        # dates don't shift (design §2).
        _, rng = await presto.query(
            f"SELECT min(quote_date), max(quote_date)"
            f" FROM {settings.reference_schema}.market_data_daily")
        start = dt.date.fromisoformat(rng[0][0])
        end = dt.date.fromisoformat(rng[0][1])
        print(f"[INFO] reference window {start} → {end}")

        await presto.query(EXT_DDL.format(schema=settings.iceberg_schema))
        _, cnt = await presto.query(
            f"SELECT count(*) FROM {settings.iceberg_schema}.market_data_daily_ext")
        if cnt[0][0] > 0:
            print(f"[OK] already loaded ({cnt[0][0]} rows) — idempotent skip")
            return

        values: List[str] = []
        for product, ticker in PRODUCTS.items():
            candles = await fetch_candles(http, product, start, end)
            kept = 0
            for ts, low, high, opn, close, vol in candles:
                d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
                if not (start <= d <= end):
                    continue
                values.append(
                    f"('{ticker}','crypto',DATE '{d}',{d.year},"
                    f"{float(opn):.4f},{float(high):.4f},{float(low):.4f},"
                    f"{float(close):.4f},{int(vol)},'USD','coinbase_public')")
                kept += 1
            print(f"[OK] {product}: {kept} daily candles in window")

        for i in range(0, len(values), 100):       # chunked inserts
            chunk = ", ".join(values[i:i + 100])
            await presto.query(
                f"INSERT INTO {settings.iceberg_schema}.market_data_daily_ext"
                f" (ticker, asset_class, quote_date, quote_year, open_price,"
                f" high_price, low_price, close_price, volume, currency,"
                f" source) VALUES {chunk}")
        print(f"[OK] loaded {len(values)} crypto bars into "
              f"{settings.iceberg_schema}.market_data_daily_ext")
    finally:
        await http.aclose()
        await presto.close()


if __name__ == "__main__":
    asyncio.run(main())
