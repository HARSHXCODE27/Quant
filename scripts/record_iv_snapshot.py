#!/usr/bin/env python3
"""
Daily IV snapshot — run once a day, ideally near market close (~15:45 IST,
same reasoning as the paper-trading journal: candles/quotes should be
settled, not mid-session). Records one ATM-IV row per F&O symbol to
logs/iv_history/{symbol}.csv. Safe to re-run same-day (replaces, not
duplicates, that day's row). See src/iv_recorder.py and README Stage 8f.

    python scripts/record_iv_snapshot.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import get_kite
from src.trend_universe import load_trend_universe
from src.iv_recorder import record_all


def main():
    kite = get_kite()
    universe = load_trend_universe(kite=kite)
    symbols = universe["symbol"].tolist()
    print(f"Recording IV snapshot for {len(symbols)} F&O symbols...")
    record_all(symbols, kite)


if __name__ == "__main__":
    main()
