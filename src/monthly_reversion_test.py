# src/monthly_reversion_test.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def analyze_monthly_range_memory(symbol):
    """
    Tests whether a month's range_pct predicts the NEXT month's range_pct —
    specifically, does an outlier month (>90th or <25th percentile) tend to be
    followed by reversion toward the median, or does the pattern persist?
    """
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        return None

    monthly = pd.read_excel(path, sheet_name="Monthly Range")
    if len(monthly) < 15:
        return None  # too few months to trust this test

    median_range = monthly["range_pct"].median()
    p25 = monthly["range_pct"].quantile(0.25)
    p90 = monthly["range_pct"].quantile(0.90)

    rows = []
    for i in range(len(monthly) - 1):
        this_month = monthly.iloc[i]
        next_month = monthly.iloc[i + 1]

        if this_month["range_pct"] > p90:
            category = "WIDE_OUTLIER"
        elif this_month["range_pct"] < p25:
            category = "NARROW_OUTLIER"
        else:
            continue  # only interested in outlier months

        rows.append({
            "this_month_range": this_month["range_pct"],
            "next_month_range": next_month["range_pct"],
            "category": category,
        })

    if not rows:
        return None

    df = pd.DataFrame(rows)

    wide_next_avg = df[df["category"] == "WIDE_OUTLIER"]["next_month_range"].mean()
    narrow_next_avg = df[df["category"] == "NARROW_OUTLIER"]["next_month_range"].mean()

    return {
        "symbol": symbol,
        "median_range": round(median_range, 2),
        "count_wide_outliers": (df["category"] == "WIDE_OUTLIER").sum(),
        "avg_next_month_after_wide": round(wide_next_avg, 2) if pd.notna(wide_next_avg) else None,
        "count_narrow_outliers": (df["category"] == "NARROW_OUTLIER").sum(),
        "avg_next_month_after_narrow": round(narrow_next_avg, 2) if pd.notna(narrow_next_avg) else None,
    }

def run_monthly_reversion_test(symbol_list):
    results = [analyze_monthly_range_memory(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])