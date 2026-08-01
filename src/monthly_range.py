# src/monthly_range.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def compute_monthly_range(df):
    """
    For each calendar month, computes:
    - range_pct: total high-low swing as % of month's open
    - net_move_pct: where the month ended up vs where it started
    - up_move_pct: furthest price pushed ABOVE the month's open
    - down_move_pct: furthest price pushed BELOW the month's open
    """
    df = df.copy()
    df["year_month"] = df.index.to_period("M")

    monthly = df.groupby("year_month").agg(
        month_open=("open", "first"),
        month_high=("high", "max"),
        month_low=("low", "min"),
        month_close=("close", "last"),
        candles=("close", "count")
    )

    monthly["range_pct"] = (monthly["month_high"] - monthly["month_low"]) / monthly["month_open"] * 100
    monthly["net_move_pct"] = (monthly["month_close"] - monthly["month_open"]) / monthly["month_open"] * 100
    monthly["up_move_pct"] = (monthly["month_high"] - monthly["month_open"]) / monthly["month_open"] * 100
    monthly["down_move_pct"] = (monthly["month_open"] - monthly["month_low"]) / monthly["month_open"] * 100

    for col in ["range_pct", "net_move_pct", "up_move_pct", "down_move_pct"]:
        monthly[col] = monthly[col].round(2)

    monthly = monthly.reset_index()
    monthly["year_month"] = monthly["year_month"].astype(str)

    return monthly

def save_monthly_range(monthly_df, symbol):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_monthly_range.csv")
    monthly_df.to_csv(path, index=False)
    print(f"Saved {len(monthly_df)} months to {path}")
    return path