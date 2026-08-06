import os
import time
import pandas as pd
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

def get_instrument_token(kite, symbol, exchange="NSE"):
    """Look up the numeric instrument_token Kite needs, from a tradingsymbol like 'BHARTIARTL'."""
    instruments = kite.instruments(exchange)
    for inst in instruments:
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Symbol '{symbol}' not found on {exchange}")

def fetch_historical_data(kite, instrument_token, from_date, to_date, interval="4hour"):
    """
    Pulls candles in chunks, since Kite caps each request at ~400 days for this
    interval. Kite's historical data endpoint is rate-limited to 3 requests/second
    (no daily cap) - a 0.35s pause between chunks keeps any single multi-chunk
    fetch safely under that, regardless of how many chunks a wide from/to window
    needs. This didn't matter for the 4H/1H pipelines (short enough windows to
    rarely need more than 1-2 chunks), but a long 1D lookback (e.g. the pledged-
    securities screener's several-year windows) can need 5-10+ chunks for one
    symbol, which hit `NetworkException: Too many requests` with no pacing here.
    """
    all_candles = []
    chunk_start = from_date
    first_chunk = True

    while chunk_start < to_date:
        chunk_end = min(chunk_start + timedelta(days=395), to_date)

        if not first_chunk:
            time.sleep(0.35)
        first_chunk = False

        print(f"Fetching {chunk_start.date()} to {chunk_end.date()}...")

        data = kite.historical_data(
            instrument_token=instrument_token,
            from_date=chunk_start,
            to_date=chunk_end,
            interval=interval
        )
        all_candles.extend(data)
        chunk_start = chunk_end + timedelta(days=1)

    df = pd.DataFrame(all_candles)
    df.drop_duplicates(subset="date", inplace=True)
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

def save_raw_data(df, symbol, interval="4hour"):
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    path = os.path.join(RAW_DATA_DIR, f"{symbol}_{interval}.csv")
    df.to_csv(path, index=False)
    print(f"Saved {len(df)} candles to {path}")
    return path