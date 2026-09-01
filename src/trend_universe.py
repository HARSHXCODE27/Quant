# src/trend_universe.py
#
# RENAMED from pledged_securities.py (see README Stage 10 for the original
# story) — this used to load a 154-symbol curated universe of securities
# eligible for pledging as broker collateral, from a hand-cleaned Excel
# workbook (data/processed/Zerodha_Approved_Securities_Cleaned.xlsx, now
# deleted — nothing still reads it). The strategy this module feeds turned
# out to be a general one — buy a share on a fresh 1D Supertrend UP flip,
# hold, exit on the opposite DOWN flip, pure cash equity, no F&O instrument
# involved — not something specific to pledged collateral, so both the file
# and its functions are renamed to match what they actually do now: build
# the full F&O stock+index trend-following universe.

import os
import pandas as pd

from src.instruments import get_fno_stock_list, INDEX_SYMBOLS

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
UNIVERSE_CACHE = os.path.join(CONFIG_DIR, "trend_universe.csv")


def load_trend_universe(kite=None, fno_symbol_list=None):
    """
    Returns a DataFrame: symbol, security_type ("Stock" or "Index").

    Three ways to get the stock portion, in order of preference:
      1. fno_symbol_list passed directly (e.g. already fetched elsewhere in
         the same session) — used as-is.
      2. kite passed — calls get_fno_stock_list(kite) live.
      3. neither passed — falls back to the on-disk cache
         (config/trend_universe.csv, written by save_trend_universe()
         below) so read-only notebooks (13, 18) never need a live Kite
         session just to know what the universe is.

    get_fno_stock_list() already returns 5 index names as pseudo-stocks —
    NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 all have their own index
    futures on NFO (confirmed directly against config/fno_stock_list.csv;
    SENSEX does NOT appear there — its futures trade on BFO, not NFO). These
    are stripped from the stock list and the canonical 6-index list
    (src.instruments.INDEX_SYMBOLS) is appended as its own "Index" rows
    instead, so no index is silently mis-typed as a "Stock" or double-counted.
    """
    if fno_symbol_list is not None:
        stock_list = list(fno_symbol_list)
    elif kite is not None:
        stock_list = get_fno_stock_list(kite)
    elif os.path.exists(UNIVERSE_CACHE):
        return pd.read_csv(UNIVERSE_CACHE)
    else:
        raise FileNotFoundError(
            f"{UNIVERSE_CACHE} not found and no kite/fno_symbol_list given — "
            "pass a live kite session at least once to build the cache "
            "(see save_trend_universe())."
        )

    index_names = set(INDEX_SYMBOLS.keys())
    stock_list = [s for s in stock_list if s not in index_names]

    combined = pd.DataFrame(
        [{"symbol": s, "security_type": "Stock"} for s in sorted(set(stock_list))]
        + [{"symbol": s, "security_type": "Index"} for s in INDEX_SYMBOLS]
    )
    return combined


def save_trend_universe(kite=None, fno_symbol_list=None):
    """Builds the universe (live) and writes the on-disk cache read-only notebooks rely on."""
    universe = load_trend_universe(kite=kite, fno_symbol_list=fno_symbol_list)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    universe.to_csv(UNIVERSE_CACHE, index=False)
    print(f"Saved {len(universe)} symbols ({(universe.security_type=='Stock').sum()} stocks, "
          f"{(universe.security_type=='Index').sum()} indices) to {UNIVERSE_CACHE}")
    return UNIVERSE_CACHE


def get_symbol_list(kite=None, fno_symbol_list=None):
    """Just the symbol column, as a plain list — convenience for pipeline calls."""
    return load_trend_universe(kite=kite, fno_symbol_list=fno_symbol_list)["symbol"].tolist()
