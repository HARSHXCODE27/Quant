# src/supertrend.py
import os
import pandas as pd
import pandas_ta as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESSED_DATA_DIR = os.path.join(PROJECT_ROOT, "data", "processed")

def load_raw_data(symbol, interval="4hour"):
    path = os.path.join(PROJECT_ROOT, "data", "raw", f"{symbol}_{interval}.csv")
    df = pd.read_csv(path, parse_dates=["date"])
    df.set_index("date", inplace=True)
    return df

def apply_supertrend(df, period=10, multiplier=3):
    """Adds Supertrend columns to df. Uses standard defaults (10, 3) — same as most charting platforms, including Kite's."""
    st = ta.supertrend(high=df["high"], low=df["low"], close=df["close"],
                        length=period, multiplier=multiplier)
    df = df.join(st)
    return df

def save_processed_data(df, symbol, interval="4hour"):
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    path = os.path.join(PROCESSED_DATA_DIR, f"{symbol}_{interval}_supertrend.csv")
    df.to_csv(path)
    print(f"Saved {len(df)} rows to {path}")
    return path