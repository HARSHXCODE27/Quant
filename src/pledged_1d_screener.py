# src/pledged_1d_screener.py
#
# NEW live screener for the pledged-securities 1D universe, parallel to
# daily_screener.py - reads exports/pledged_1d/ instead of the top-level
# exports/ folder, and additionally reports security_type/etf_category/
# directly_fno_tradable per symbol (from pledged_securities.py), since what
# a flip means to DO about it differs by type - see
# pledged_securities.load_pledged_universe()'s docstring for the full
# reasoning. This screener only reports trend state - it does not decide
# or recommend a trade.

import os
import pandas as pd
from datetime import datetime

from src.pledged_securities import load_pledged_universe

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "pledged_1d")


def check_trend_status(symbol, universe_df=None):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        print(f"No report found for {symbol} - refresh it first")
        return None

    trades = pd.read_excel(path, sheet_name="Flips")
    summary = pd.read_excel(path, sheet_name="Summary")

    open_trade = trades[trades["status"] == "OPEN"]
    if open_trade.empty:
        return None
    open_trade = open_trade.iloc[0]

    entry_date = pd.to_datetime(open_trade["entry_date"]).tz_localize(None)
    age_days = (datetime.now() - entry_date).days

    def get_metric(name):
        row = summary[summary["metric"] == name]
        return row["value"].values[0] if not row.empty else None

    median_dur = get_metric("Median duration (days)")
    p75_dur = get_metric("75th percentile duration (days)")
    p90_dur = get_metric("90th percentile duration (days)")

    result = {
        "symbol": symbol,
        "direction": open_trade["direction"],
        "trend_age_days": age_days,
        "median_duration": median_dur,
        "past_median": age_days > median_dur if median_dur else None,
        "past_75th_pct": age_days > p75_dur if p75_dur else None,
        "past_90th_pct": age_days > p90_dur if p90_dur else None,
    }

    if universe_df is not None:
        match = universe_df[universe_df["symbol"] == symbol]
        if not match.empty:
            result["security_type"] = match["security_type"].values[0]
            result["etf_category"] = match["etf_category"].values[0]
            result["directly_fno_tradable"] = bool(match["directly_fno_tradable"].values[0])

    return result


def screen_list(symbol_list):
    """
    Same shape as daily_screener.screen_list - loads the pledged universe
    once (not per-symbol) for the type/category/F&O-tradable columns.
    """
    universe_df = load_pledged_universe()
    results = [check_trend_status(s, universe_df=universe_df) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])
