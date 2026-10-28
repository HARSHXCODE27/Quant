#!/usr/bin/env python3
"""
One-off fetch of 5-minute candles for the intraday test (src/intraday_test.py,
README Stage 8h). Kite caps 5-minute requests at 100 days, so this chunks at
95. Writes data/raw/{symbol}_5minute.csv. Skips symbols already fetched.

    python scripts/fetch_5minute.py               # NIFTY, BANKNIFTY + top 20 ranked
    python scripts/fetch_5minute.py --top 40
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from scripts.daily_list import shortlist_symbols
from src.auth import get_kite
from src.instruments import build_nse_token_lookup, get_index_token

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "raw")
START = datetime(2023, 1, 1)
INDEX_SYMBOLS = {"NIFTY": ("NIFTY 50", "NSE"), "BANKNIFTY": ("NIFTY BANK", "NSE")}


def fetch(kite, token, start, end):
    rows, cur = [], start
    while cur < end:
        stop = min(cur + timedelta(days=95), end)
        rows.extend(kite.historical_data(token, cur, stop, "5minute"))
        cur = stop + timedelta(days=1)
        time.sleep(0.35)
    df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    symbols = ["NIFTY", "BANKNIFTY"] + [s for s in shortlist_symbols(args.top)
                                        if s not in ("NIFTY", "BANKNIFTY")]
    kite = get_kite()
    lookup = build_nse_token_lookup(kite)
    end = datetime.now()
    for s in symbols:
        path = os.path.join(RAW_DIR, f"{s}_5minute.csv")
        if os.path.exists(path):
            continue
        token = (get_index_token(kite, *INDEX_SYMBOLS[s]) if s in INDEX_SYMBOLS
                 else lookup.get(s))
        if token is None:
            print(f"{s}: no token")
            continue
        try:
            df = fetch(kite, token, START, end)
            df.to_csv(path, index=False)
            print(f"{s}: {len(df)} candles, {df['date'].iloc[0]:%Y-%m-%d} to {df['date'].iloc[-1]:%Y-%m-%d}")
        except Exception as e:
            print(f"{s}: {e}")


if __name__ == "__main__":
    main()
