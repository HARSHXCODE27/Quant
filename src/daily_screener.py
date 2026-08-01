# src/daily_screener.py
import os
import pandas as pd
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def check_trend_status(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        print(f"No report found for {symbol}")
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

    return {
        "symbol": symbol,
        "direction": open_trade["direction"],
        "trend_age_days": age_days,
        "median_duration": median_dur,
        "past_median": age_days > median_dur if median_dur else None,
        "past_75th_pct": age_days > p75_dur if p75_dur else None,
    }

def screen_list(symbol_list):
    results = [check_trend_status(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])