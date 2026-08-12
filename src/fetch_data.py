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

def save_raw_data(df, symbol, interval="4hour", allow_shrink=False):
    """
    SAFETY GUARD (added after the same silent-data-destruction pattern kept
    recurring across different pipelines - most recently even AFTER a
    per-pipeline incremental fix, when a stale Jupyter kernel ran an old,
    unguarded code path that bypassed the fix entirely because it never
    even called the new function). Every previous fix added the protection
    to one specific "incremental" function per pipeline
    (pledged_1d_pipeline.py, debit_spread_scale_pipeline.py,
    option_buying_scale_pipeline.py, scale_pipeline.py) - which only helps
    if that exact function is what actually runs. A stale kernel, an
    un-restarted notebook, or any future pipeline that forgets to add its
    own check can still call the OLD full-replace function and silently
    destroy history, bypassing every guard built so far.

    This function is the one place every pipeline actually calls to
    persist raw price data - moving the guard here means it can't be
    bypassed by which higher-level function happens to run. Before
    overwriting an existing file, compares the new data's earliest date
    against the existing file's earliest date. If the new data would cover
    meaningfully LESS history (starts more than 5 days later than what's
    already saved), refuses to save and raises instead of silently
    destroying it - this is never a legitimate outcome in this project's
    normal usage, since even a genuine deep refresh should cover at least
    as much history as before, not less. Pass allow_shrink=True to
    override deliberately (e.g. intentionally resetting a symbol).

    A corrupted/unreadable existing file (e.g. the 1-byte ADANIENSOL_trades
    incident, though that's a different file - same principle would apply
    here to a corrupted raw CSV) is treated as "nothing to protect" rather
    than blocking forever - the fresh save is let through, which naturally
    self-heals the corruption instead of getting permanently stuck.
    """
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    path = os.path.join(RAW_DATA_DIR, f"{symbol}_{interval}.csv")

    if not allow_shrink and os.path.exists(path) and "date" in df.columns and not df.empty:
        existing_earliest = None
        try:
            existing_first_row = pd.read_csv(path, usecols=["date"], nrows=1)
            if not existing_first_row.empty:
                existing_earliest = pd.to_datetime(existing_first_row["date"].iloc[0])
                if existing_earliest.tzinfo is not None:
                    existing_earliest = existing_earliest.tz_localize(None)
        except Exception:
            existing_earliest = None  # corrupted/unreadable - nothing to protect

        if existing_earliest is not None:
            new_earliest = pd.to_datetime(df["date"]).min()
            if new_earliest.tzinfo is not None:
                new_earliest = new_earliest.tz_localize(None)
            if new_earliest > existing_earliest + pd.Timedelta(days=5):
                raise ValueError(
                    f"save_raw_data refusing to overwrite {symbol}_{interval}.csv: "
                    f"existing data starts {existing_earliest.date()}, new data would "
                    f"start {new_earliest.date()} - this would SHRINK saved history. "
                    f"If a stale kernel is running old code, restart it and re-run. "
                    f"If this is deliberate, call save_raw_data(..., allow_shrink=True)."
                )

    df.to_csv(path, index=False)
    print(f"Saved {len(df)} candles to {path}")
    return path