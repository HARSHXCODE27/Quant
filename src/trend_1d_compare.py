# src/trend_1d_compare.py
#
# Cross-instrument comparison for the general F&O trend-following 1D
# universe (repurposed from the original pledged-securities scope — see
# trend_universe.py and README Stage 10), parallel to compare_stocks.py -
# reads from exports/trend_1d/ (not the top-level exports/ folder
# compare_stocks.py uses) and writes TREND_1D_COMPARISON.xlsx instead of
# ALL_STOCKS_COMPARISON.xlsx, so this never touches the existing 4H
# comparison file. Universe-agnostic — takes whatever symbol_list it's given.

import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "trend_1d")
TOP_EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")


def build_comparison_table(symbol_list):
    """
    Same pivot as compare_stocks.build_comparison_table (Summary sheet,
    metric/value rows -> one row per instrument) - reused logic, redirected
    to the trend_1d exports folder.
    """
    all_rows = []

    for symbol in symbol_list:
        path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            print(f"Skipping {symbol} — report not found")
            continue

        try:
            summary = pd.read_excel(path, sheet_name="Summary")
            row = {"symbol": symbol}
            row.update(dict(zip(summary["metric"], summary["value"])))
            all_rows.append(row)
        except Exception as e:
            print(f"Failed to read {symbol}: {e}")

    comparison = pd.DataFrame(all_rows)
    return comparison


def save_comparison(comparison_df):
    path = os.path.join(TOP_EXPORTS_DIR, "TREND_1D_COMPARISON.xlsx")
    comparison_df.to_excel(path, sheet_name="Comparison", index=False)
    print(f"Saved comparison of {len(comparison_df)} instruments to {path}")
    return path
