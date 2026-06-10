#!/usr/bin/env python3
"""TradeCrew — one command, fully unattended (REQ-020).

  python main.py                 # default pace: 1 simulated day / 5s
  python main.py --pace 0.5      # demo-fast
  python main.py --ticks 20      # cap the number of simulated days
"""
from __future__ import annotations

import argparse
import asyncio

from src.orchestrator import Session


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pace", type=float, default=None,
                    help="wall-clock seconds per simulated trading day")
    ap.add_argument("--ticks", type=int, default=None,
                    help="max simulated days (default: run stream to end)")
    args = ap.parse_args()
    session = Session()
    asyncio.run(session.run(max_ticks=args.ticks, tick_seconds=args.pace))


if __name__ == "__main__":
    main()
