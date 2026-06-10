"""Market clock tests — REQ-013, AC-1.2 (TST-001b, TST-013a)."""
import asyncio

import pytest

from src.market.clock import LookaheadError, MarketClock
from tests.fixtures import bars as fx


def make_clock(lookback=90):
    return MarketClock({"UPT": fx.uptrend()}, lookback)


def test_lookahead_raises():                      # TST-001b / AC-1.2
    clock = make_clock()
    today = clock.today()
    future = clock._dates[clock._idx + 1]
    with pytest.raises(LookaheadError):
        clock.bar("UPT", on=future)
    assert clock.bar("UPT", on=today) is not None


def test_history_never_exceeds_today():           # AC-1.2
    clock = make_clock()
    h = clock.history("UPT", 200)
    assert all(b.quote_date <= clock.today() for b in h)


def test_advance_moves_one_day():                 # REQ-013
    clock = make_clock()
    d0 = clock.today()
    d1 = clock.advance()
    assert d1 > d0


def test_exhaustion_stops():                      # session end condition
    clock = make_clock(lookback=118)              # 120 days → 1 replay step
    clock.advance()
    assert clock.exhausted
    with pytest.raises(StopIteration):
        clock.advance()


def test_shared_view_across_tasks():              # TST-013a / AC-13.1
    clock = make_clock()

    async def run():
        seen = []

        async def reader():
            for _ in range(20):
                seen.append(clock.today())
                await asyncio.sleep(0)

        await asyncio.gather(reader(), reader())
        return seen

    seen = asyncio.get_event_loop().run_until_complete(run())
    # Both readers interleave; at any await point they saw the same date
    assert len(set(seen)) == 1


def test_lookback_split():                        # design §2
    clock = make_clock(lookback=90)
    assert len(clock.history("UPT", 999)) == 91   # 90 lookback + today
