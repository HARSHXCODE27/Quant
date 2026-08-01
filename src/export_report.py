# src/export_report.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def export_full_report(trades_df, monthly_df, summary_df, symbol):
    """
    Combines Flips, Monthly Range, and Summary into a single .xlsx workbook
    with three sheets — the final per-stock deliverable.
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")

    # Excel can't store timezone-aware datetimes — strip tz for this export only,
    # same fix as before, just applied consistently here now
    trades_excel = trades_df.copy()
    trades_excel["entry_date"] = pd.to_datetime(trades_excel["entry_date"]).dt.tz_localize(None)
    trades_excel["exit_date"] = pd.to_datetime(trades_excel["exit_date"]).dt.tz_localize(None)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        trades_excel.to_excel(writer, sheet_name="Flips", index=False)
        monthly_df.to_excel(writer, sheet_name="Monthly Range", index=False)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    print(f"Saved full report to {path}")
    return path