# src/monthly_range_screener.py
import os
import pandas as pd
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def check_current_month_range(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        return None

    raw_path = os.path.join(PROJECT_ROOT, "data", "raw", f"{symbol}_4hour.csv")
    if not os.path.exists(raw_path):
        return None

    df = pd.read_csv(raw_path, parse_dates=["date"])
    df.set_index("date", inplace=True)

    now = datetime.now()
    this_month = df[(df.index.year == now.year) & (df.index.month == now.month)]
    if this_month.empty:
        return None

    month_open = this_month["open"].iloc[0]
    month_high = this_month["high"].max()
    month_low = this_month["low"].min()
    current_range_pct = round((month_high - month_low) / month_open * 100, 2)

    days_into_month = now.day

    summary = pd.read_excel(path, sheet_name="Summary")
    def get_metric(name):
        row = summary[summary["metric"] == name]
        return row["value"].values[0] if not row.empty else None

    median_range = get_metric("Median monthly range_pct")
    p75_range = get_metric("75th percentile monthly range_pct")
    p90_range = get_metric("90th percentile monthly range_pct")

    return {
        "symbol": symbol,
        "days_into_month": days_into_month,
        "current_month_range_pct": current_range_pct,
        "median_monthly_range": median_range,
        "75th_pct_monthly_range": p75_range,
        "90th_pct_monthly_range": p90_range,
        "already_past_median": current_range_pct > median_range if median_range else None,
        "already_past_75th": current_range_pct > p75_range if p75_range else None,
        "already_past_90th": current_range_pct > p90_range if p90_range else None,
    }

def screen_monthly_range(symbol_list):
    results = [check_current_month_range(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])