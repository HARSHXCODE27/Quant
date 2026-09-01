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

# The canonical 6-index universe used across this project's F&O strategies —
# matches notebooks/03_scale_all_fno.ipynb's own indices list exactly.
# tradingsymbol/exchange are what Kite's instrument dump actually uses, not
# the short symbol name (e.g. NIFTY's tradingsymbol is "NIFTY 50", not
# "NIFTY"). SENSEX trades on BSE; everything else is NSE. Centralized here
# (rather than re-declared inline per notebook) since notebook 10/12's
# trend-1D universe swap needs the same mapping notebook 03 already uses.
INDEX_SYMBOLS = {
    "NIFTY": ("NIFTY 50", "NSE"),
    "BANKNIFTY": ("NIFTY BANK", "NSE"),
    "SENSEX": ("SENSEX", "BSE"),
    "NIFTYNXT50": ("NIFTY NEXT 50", "NSE"),
    "MIDCPNIFTY": ("NIFTY MID SELECT", "NSE"),
    "FINNIFTY": ("NIFTY FIN SERVICE", "NSE"),
}

def get_index_token_lookup(kite):
    """symbol -> instrument_token for all 6 indices in INDEX_SYMBOLS."""
    return {
        symbol: get_index_token(kite, tradingsymbol, exchange)
        for symbol, (tradingsymbol, exchange) in INDEX_SYMBOLS.items()
    }