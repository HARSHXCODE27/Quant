# src/instruments.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

def get_fno_stock_list(kite):
    nfo_instruments = kite.instruments("NFO")
    df = pd.DataFrame(nfo_instruments)
    futures = df[df["instrument_type"] == "FUT"]
    stock_list = sorted(futures["name"].unique().tolist())
    return stock_list

def save_fno_list(stock_list):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    path = os.path.join(CONFIG_DIR, "fno_stock_list.csv")
    pd.DataFrame({"symbol": stock_list}).to_csv(path, index=False)
    print(f"Saved {len(stock_list)} F&O stocks to {path}")
    return path

def build_nse_token_lookup(kite):
    """
    Fetches NSE instruments ONCE and builds a symbol -> instrument_token dict.
    Reused across all 215 stocks instead of re-fetching per stock.
    """
    instruments = kite.instruments("NSE")
    df = pd.DataFrame(instruments)
    lookup = dict(zip(df["tradingsymbol"], df["instrument_token"]))
    return lookup

def get_index_token(kite, tradingsymbol, exchange="NSE"):
    """
    Looks up an index's instrument token — indices live in a different
    segment than regular stocks, so this searches separately.
    """
    instruments = kite.instruments(exchange)
    df = pd.DataFrame(instruments)
    match = df[df["tradingsymbol"] == tradingsymbol]
    if match.empty:
        raise ValueError(f"Index '{tradingsymbol}' not found on {exchange}")
    return match.iloc[0]["instrument_token"]