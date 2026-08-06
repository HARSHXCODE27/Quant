# src/scale_pipeline.py
import os
import time
import traceback
from datetime import datetime
import pandas as pd

from src.fetch_data import fetch_historical_data, save_raw_data
from src.supertrend import load_raw_data, apply_supertrend
from src.flip_analysis import detect_flips
from src.monthly_range import compute_monthly_range
from src.summary_stats import compute_summary_stats
from src.export_report import export_full_report

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

def already_done(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    return os.path.exists(path)

def process_stock(symbol, token, kite, from_date, to_date):
    df = fetch_historical_data(kite, token, from_date, to_date, interval="4hour")
    if df.empty or len(df) < 20:
        raise ValueError(f"Insufficient data ({len(df)} candles)")

    save_raw_data(df, symbol)
    df = df.set_index("date")

    df_st = apply_supertrend(df)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(df)
    summary = compute_summary_stats(trades, monthly)
    export_full_report(trades, monthly, summary, symbol)

def process_stock_incremental(symbol, token, kite, to_date,
                                deep_from_date=datetime(2022, 1, 1),
                                quick_lookback_days=120):
    """
    Efficiency fix for the daily credit-spread screener (notebook 06) - NOT
    a correctness bug like the ones found and fixed in the debit spread/
    option buying/pledged pipelines. notebook 06's refresh cell already
    used the SAME deep from_date=2022-01-01 window as the monthly full-scale
    notebook 02, so it was never silently shrinking history - checked this
    directly before touching anything. But it WAS wasteful: every daily
    screener run re-downloads ~4 years of 4H data for its ~16-symbol
    shortlist instead of just catching up on what's missing since the last
    save, which is slower and heavier on Kite's rate limit than necessary
    for a check that just runs once a day.

    Same merge pattern as the other three incremental fixes: loads existing
    raw 4H data if any, fetches only the recent catch-up window
    (quick_lookback_days), merges onto existing history (dedup on date,
    sorted), and includes the same shrink-guard (refuses to save if the
    merge would cover less history than what already existed). Only does a
    genuine deep fetch (deep_from_date) the first time a symbol has no
    saved data at all.
    """
    try:
        existing = load_raw_data(symbol)
    except FileNotFoundError:
        existing = None

    if existing is None or existing.empty:
        fetch_from = deep_from_date
    else:
        last_saved = pd.Timestamp(existing.index.max())
        if last_saved.tzinfo is not None:
            last_saved = last_saved.tz_localize(None)
        fetch_from = (last_saved - pd.Timedelta(days=quick_lookback_days)).to_pydatetime()

    new_df = fetch_historical_data(kite, token, fetch_from, to_date, interval="4hour")
    if new_df.empty:
        raise ValueError("No data returned from fetch")

    def _to_naive(series):
        series = pd.to_datetime(series)
        return series.dt.tz_localize(None) if series.dt.tz is not None else series

    new_df["date"] = _to_naive(new_df["date"])

    if existing is not None and not existing.empty:
        existing_reset = existing.reset_index()
        existing_reset["date"] = _to_naive(existing_reset["date"])
        combined = pd.concat([existing_reset, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)

        existing_earliest = existing_reset["date"].min()
        combined_earliest = combined["date"].min()
        if pd.notna(existing_earliest) and combined_earliest > existing_earliest + pd.Timedelta(days=5):
            raise ValueError(
                f"{symbol}: incremental merge would SHRINK saved history "
                f"(existing started {existing_earliest.date()}, merge result "
                f"would start {combined_earliest.date()}) — refusing to save. "
                f"Re-run notebook 02 (deep refresh) for this symbol instead."
            )
    else:
        combined = new_df.sort_values("date").reset_index(drop=True)

    save_raw_data(combined, symbol)
    combined_indexed = combined.set_index("date")

    if len(combined_indexed) < 20:
        raise ValueError(f"Insufficient data ({len(combined_indexed)} candles)")

    df_st = apply_supertrend(combined_indexed)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(combined_indexed)
    summary = compute_summary_stats(trades, monthly)
    export_full_report(trades, monthly, summary, symbol)

def run_all_stocks(kite, token_lookup, stock_list, from_date, to_date, delay_seconds=0.4, force_refresh=False):
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, "scale_run_log.csv")

    results = []
    total = len(stock_list)

    for i, symbol in enumerate(stock_list, start=1):
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
            process_stock(symbol, token, kite, from_date, to_date)
            results.append({"symbol": symbol, "status": "SUCCESS", "error": ""})
            print(f"[{i}/{total}] {symbol} — done")
        except Exception as e:
            error_msg = str(e)
            print(f"[{i}/{total}] {symbol} — FAILED: {error_msg}")
            results.append({"symbol": symbol, "status": "FAILED", "error": error_msg})
            with open(os.path.join(LOGS_DIR, "error_details.log"), "a") as f:
                f.write(f"\n--- {symbol} at {datetime.now()} ---\n")
                f.write(traceback.format_exc())

        time.sleep(delay_seconds)
        pd.DataFrame(results).to_csv(log_path, index=False)

    print(f"\nDone. {sum(r['status']=='SUCCESS' for r in results)}/{total} succeeded.")
    return pd.DataFrame(results)

def reprocess_stock(symbol):
    df = load_raw_data(symbol)
    df_st = apply_supertrend(df)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(df)
    summary = compute_summary_stats(trades, monthly)
    export_full_report(trades, monthly, summary, symbol)

def reprocess_all(stock_list):
    total = len(stock_list)
    for i, symbol in enumerate(stock_list, start=1):
        try:
            reprocess_stock(symbol)
            print(f"[{i}/{total}] {symbol} — updated")
        except Exception as e:
            print(f"[{i}/{total}] {symbol} — FAILED: {e}")