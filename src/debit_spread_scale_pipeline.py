# src/debit_spread_scale_pipeline.py
#
# NEW batch runner for the debit spread strategy (Stage 9), parallel to
# scale_pipeline.py + compare_stocks.py - NOT a modification of either.
# Those scale flip_analysis's regime-following trades across the F&O
# universe on 4H data; this scales ema_adx_signal + debit_spread_trades
# instead, on 1H data, and aggregates win-rate/avg-R per instrument so the
# FULL UNIVERSE's distribution - not 3 hand-picked stocks - answers whether
# this strategy's signal quality actually holds up before trusting it.
#
# Same operational discipline as scale_pipeline.py: resume support (skip
# already-done), isolated failure handling (one bad instrument doesn't
# kill the run), rate-limit delay, incremental log writes.

import os
import time
import traceback
from datetime import datetime
import pandas as pd

from src.fetch_data import fetch_historical_data, save_raw_data
from src.supertrend import load_raw_data
from src.ema_adx_signal import detect_signals
from src.debit_spread_trades import simulate_trades, summarize_trades, save_trades

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "debit_spread")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

def already_done(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_trades.csv")
    return os.path.exists(path)

def process_instrument(symbol, token, kite, from_date, to_date):
    """
    from_date should already include a ~6-week warm-up buffer before the
    date you actually want signals from - EMA/ADX need real history to
    stabilize before their values are trustworthy (see README assumptions
    log for the underlying finding). This function does NOT trim that
    buffer off automatically - it's cheap insurance, not wasted data.
    """
    df = fetch_historical_data(kite, token, from_date, to_date, interval="60minute")
    if df.empty or len(df) < 100:
        raise ValueError(f"Insufficient data ({len(df)} candles)")

    save_raw_data(df, symbol, interval="60minute")
    df = df.set_index("date")

    df = detect_signals(df)
    trades = simulate_trades(df)
    save_trades(trades, symbol)

    summary = summarize_trades(trades)
    summary["symbol"] = symbol
    return summary

def run_all_instruments(kite, token_lookup, symbol_list, from_date, to_date,
                         delay_seconds=0.4, force_refresh=False):
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, "debit_spread_scale_run_log.csv")

    results = []
    total = len(symbol_list)

    for i, symbol in enumerate(symbol_list, start=1):
        if already_done(symbol) and not force_refresh:
            print(f"[{i}/{total}] {symbol} — already done, skipping")
            results.append({"symbol": symbol, "status": "SKIPPED_ALREADY_DONE", "error": ""})
            continue

        token = token_lookup.get(symbol)
        if token is None:
            print(f"[{i}/{total}] {symbol} — no NSE token found, skipping")
            results.append({"symbol": symbol, "status": "FAILED", "error": "No NSE instrument token found"})
            continue

        try:
            print(f"[{i}/{total}] {symbol} — processing...")
            summary = process_instrument(symbol, token, kite, from_date, to_date)
            summary["status"] = "SUCCESS"
            summary["error"] = ""
            results.append(summary)
            print(f"[{i}/{total}] {symbol} — done "
                  f"(trades={summary.get('closed_trades')}, "
                  f"win_rate={summary.get('win_rate_pct')}, "
                  f"avg_r={summary.get('avg_r_achieved')})")
        except Exception as e:
            error_msg = str(e)
            print(f"[{i}/{total}] {symbol} — FAILED: {error_msg}")
            results.append({"symbol": symbol, "status": "FAILED", "error": error_msg})
            with open(os.path.join(LOGS_DIR, "debit_spread_error_details.log"), "a") as f:
                f.write(f"\n--- {symbol} at {datetime.now()} ---\n")
                f.write(traceback.format_exc())

        time.sleep(delay_seconds)
        pd.DataFrame(results).to_csv(log_path, index=False)

    results_df = pd.DataFrame(results)
    succeeded = int((results_df["status"] == "SUCCESS").sum()) if "status" in results_df else 0
    print(f"\nDone. {succeeded}/{total} succeeded.")
    return results_df

def reprocess_instrument(symbol):
    """Recompute-only refresh (no API call) - reuses already-saved raw 1H data."""
    df = load_raw_data(symbol, interval="60minute")
    df = detect_signals(df)
    trades = simulate_trades(df)
    save_trades(trades, symbol)
    summary = summarize_trades(trades)
    summary["symbol"] = symbol
    return summary

def build_comparison(results_df):
    """
    Takes the results_df from run_all_instruments (or a reload of
    logs/debit_spread_scale_run_log.csv) and produces one clean row per
    successfully-processed instrument - the table that actually answers
    "does signal quality hold up across the universe", not just on 3
    hand-picked stocks.
    """
    if "status" not in results_df.columns:
        return pd.DataFrame()

    ok = results_df[results_df["status"] == "SUCCESS"].copy()
    cols = ["symbol", "total_trades", "closed_trades", "win_rate_pct",
            "avg_r_achieved", "median_r_achieved", "median_candles_held"]
    cols = [c for c in cols if c in ok.columns]
    return ok[cols].sort_values("avg_r_achieved", ascending=False).reset_index(drop=True)

def save_comparison(comparison_df):
    path = os.path.join(PROJECT_ROOT, "exports", "DEBIT_SPREAD_COMPARISON.xlsx")
    comparison_df.to_excel(path, sheet_name="Comparison", index=False)
    print(f"Saved debit spread comparison of {len(comparison_df)} instruments to {path}")
    return path
