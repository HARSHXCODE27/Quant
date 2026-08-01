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