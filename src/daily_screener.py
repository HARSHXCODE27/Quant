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
    p90_dur = get_metric("90th percentile duration (days)")

    # runway_left_* = checkpoint - age_days: how many more days until this
    # trend's age would reach that percentile of its OWN history, given
    # where it already stands. Purely descriptive, same as past_median/
    # past_75th_pct/past_90th_pct below - NOT a predictive claim. Negative
    # means the trend has already run past that checkpoint (which tested
    # findings show is NOT a reversal warning - see the note below), it
    # just means there's no "runway" left relative to that particular
    # percentile of history. Added because trend_age_days alone tells you
    # how long a trend has run but not how that compares to what's typical
    # in one glance - this makes that comparison direct instead of implicit
    # across three separate booleans, same spirit as the debit-spread/
    # option-buying screeners' candles_left_before_time_exit.
    def runway(checkpoint):
        return round(checkpoint - age_days, 1) if checkpoint is not None else None

    # NOTE: past_median/past_75th_pct/past_90th_pct (and runway_left_*
    # above) are descriptive only - how this trade's age compares to the
    # stock's own history. Tested findings (reversion_test.py,
    # exhaustion_test.py) show crossing these checkpoints does NOT predict
    # an imminent reversal or give a reliable read on remaining time either
    # way - don't read "True" or a negative runway here as a warning or an
    # exit signal.
    return {
        "symbol": symbol,
        "direction": open_trade["direction"],
        "trend_age_days": age_days,
        "median_duration": median_dur,
        "past_median": age_days > median_dur if median_dur else None,
        "past_75th_pct": age_days > p75_dur if p75_dur else None,
        "past_90th_pct": age_days > p90_dur if p90_dur else None,
        "runway_left_vs_median": runway(median_dur),
        "runway_left_vs_p75": runway(p75_dur),
        "runway_left_vs_p90": runway(p90_dur),
    }

def screen_list(symbol_list):
    results = [check_trend_status(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])