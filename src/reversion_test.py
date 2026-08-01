# src/reversion_test.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def analyze_duration_memory(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        return None

    trades = pd.read_excel(path, sheet_name="Flips")
    closed = trades[trades["status"] == "CLOSED"].copy()
    if len(closed) < 15:
        return None

    closed["duration_days"] = pd.to_timedelta(closed["duration"]).dt.total_seconds() / 86400
    median_dur = closed["duration_days"].median()

    crossed = closed[closed["duration_days"] > median_dur].copy()
    if len(crossed) < 5:
        return None

    crossed["excess_days"] = crossed["duration_days"] - median_dur
    avg_excess = crossed["excess_days"].mean()
    ratio = round(avg_excess / median_dur, 2)

    return {
        "symbol": symbol,
        "median_duration": round(median_dur, 1),
        "flips_crossed_median": len(crossed),
        "avg_excess_days_after_median": round(avg_excess, 1),
        "expected_total_duration_if_crossed": round(median_dur + avg_excess, 1),
        "excess_to_median_ratio": ratio,
    }

def run_reversion_test(symbol_list):
    results = [analyze_duration_memory(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])