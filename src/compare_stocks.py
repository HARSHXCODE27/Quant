# src/compare_stocks.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def build_comparison_table(symbol_list):
    """
    Reads the Summary sheet from every stock's full_report.xlsx and pivots
    them into one table — one row per stock, one column per metric.
    """
    all_rows = []

    for symbol in symbol_list:
        path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            print(f"Skipping {symbol} — report not found")
            continue

        try:
            summary = pd.read_excel(path, sheet_name="Summary")
            # summary is currently (metric, value) rows — flip it into one row: {symbol, metric1: val1, metric2: val2, ...}
            row = {"symbol": symbol}
            row.update(dict(zip(summary["metric"], summary["value"])))
            all_rows.append(row)
        except Exception as e:
            print(f"Failed to read {symbol}: {e}")

    comparison = pd.DataFrame(all_rows)
    return comparison

def save_comparison(comparison_df):
    path = os.path.join(EXPORTS_DIR, "ALL_STOCKS_COMPARISON.xlsx")
    comparison_df.to_excel(path, sheet_name="Comparison", index=False)
    print(f"Saved comparison of {len(comparison_df)} stocks to {path}")
    return path