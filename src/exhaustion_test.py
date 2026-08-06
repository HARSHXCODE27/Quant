# src/exhaustion_test.py
#
# NEW test, parallel to reversion_test.py — but a different QUESTION.
# reversion_test.py asks: at ENTRY, does an already-aged trend predict
# reversal? (Answer: no — momentum, ~13-15% longer, see README.) That
# finding already covers the MEDIAN checkpoint's average excess and feeds
# trend_age_note as a mild entry-side "don't bet against it" note.
#
# This test asks a DIFFERENT question, for an already-OPEN credit spread
# position: once a trend has crossed a checkpoint, how much MORE time
# typically remains, and is that remaining time tightly clustered enough
# to act on as a real exhaustion/profit-booking signal? This is NOT an
# entry signal and must never be read as one — trend_age_note (entry) and
# whatever this test finds (exit) answer two different questions and
# should never be conflated or have one overwrite the other.
#
# What's actually NEW here vs reversion_test.py:
#   1. the 75th and 90th percentile checkpoints (reversion_test.py only
#      ever tested the median)
#   2. the SPREAD of the excess, not just its average — reversion_test.py
#      reported avg_excess_days/ratio only; this reports std/percentiles
#      AND a survival-style "% ended within X more" curve, since that's
#      what actually answers "is this tight enough to act on."
#
# Checkpoints are NESTED, not independent: any flip crossing the 90th
# percentile duration has, by construction, already crossed the 75th
# percentile and the median too. The three checkpoint rows are not three
# separate samples of flips — read them as increasingly-strict subsets of
# the same underlying flips.
#
# Excess is pooled as a RATIO of the checkpoint (excess_days /
# checkpoint_days), not raw days, before combining across the universe.
# Raw days would mix a stock with a 10-day median with a stock with a
# 60-day median and misread pure scale difference as scatter/unpredictability.
# Raw days are still kept in the per-stock table for reference, but the
# universe-level verdict is judged on the ratio distribution.
#
# CAVEAT (state this plainly, don't bury it): each stock's OWN 90th
# percentile duration is itself computed from a small sample (same >=15
# closed-flips floor as reversion_test.py) — for many stocks that's 1-3
# tail observations deciding where the p90 checkpoint sits. Even a
# tight-looking p90 result should be read with that in mind — same
# caution already applied to outlier-reliant stocks in the debit spread
# scorer (avg-vs-median gap flag).

import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

CHECKPOINTS = {
    "median": "Median duration (days)",
    "p75": "75th percentile duration (days)",
    "p90": "90th percentile duration (days)",
}

MIN_CLOSED_FLIPS = 15  # same floor as reversion_test.py


def _get_checkpoint_values(summary_df):
    def get_metric(name):
        row = summary_df[summary_df["metric"] == name]
        return row["value"].values[0] if not row.empty else None
    return {label: get_metric(col) for label, col in CHECKPOINTS.items()}


def _duration_to_days(duration_series):
    """
    The Flips sheet's `duration` column is written as a pandas Timedelta,
    but once round-tripped through Excel (export_report.py -> read back
    here), pandas/openpyxl hands it back as a plain float already
    expressed in days (e.g. 15.166667) — NOT a timedelta string. Calling
    pd.to_timedelta() on that float defaults to nanosecond units and
    silently produces near-zero everything (confirmed against ABB's real
    export: median_duration came back as 0.0). Handle both shapes so this
    is correct regardless of how a given file happens to load.
    """
    if pd.api.types.is_numeric_dtype(duration_series):
        return duration_series.astype(float)
    return pd.to_timedelta(duration_series).dt.total_seconds() / 86400


def analyze_exhaustion_for_symbol(symbol):
    """
    Per-stock pass: for each checkpoint, finds closed flips that crossed it
    and records one row per (symbol, checkpoint, individual crossing flip) —
    excess_days AND excess_ratio. Returns a flat list of these raw crossing
    records (not a per-stock summary) — run_exhaustion_test() pools them
    across the universe, since the universe-level ratio distribution is
    what the verdict is actually judged on, not any single stock's own count.
    """
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        return None

    trades = pd.read_excel(path, sheet_name="Flips")
    summary = pd.read_excel(path, sheet_name="Summary")

    closed = trades[trades["status"] == "CLOSED"].copy()
    if len(closed) < MIN_CLOSED_FLIPS:
        return None

    closed["duration_days"] = _duration_to_days(closed["duration"])
    checkpoints = _get_checkpoint_values(summary)

    rows = []
    for label, checkpoint_days in checkpoints.items():
        if checkpoint_days is None or checkpoint_days <= 0:
            continue
        crossed = closed[closed["duration_days"] > checkpoint_days].copy()
        if crossed.empty:
            continue
        crossed["excess_days"] = crossed["duration_days"] - checkpoint_days
        crossed["excess_ratio"] = crossed["excess_days"] / checkpoint_days
        for _, r in crossed.iterrows():
            rows.append({
                "symbol": symbol,
                "checkpoint": label,
                "checkpoint_days": round(checkpoint_days, 1),
                "excess_days": round(r["excess_days"], 2),
                "excess_ratio": round(r["excess_ratio"], 3),
            })
    return rows if rows else None


def run_exhaustion_test(symbol_list):
    """
    Runs analyze_exhaustion_for_symbol across the universe and returns
    (per_stock_summary, universe_summary):

    - per_stock_summary: one row per stock per checkpoint (crossed_count,
      avg/median excess_days, avg/median excess_ratio) — reference only,
      for spot-checking an individual stock, NOT what the verdict is based on.

    - universe_summary: one row per checkpoint, pooling every individual
      crossing flip across the whole universe — mean/median/std/p25/p75 of
      excess_ratio, plus a survival curve (pct_ended_within_X_more) showing
      what fraction of crossings fully closed within 25%/50%/75%/100%
      additional time beyond the checkpoint. THIS table is what the verdict
      (tight/actionable vs scattered/not actionable) should be read from.
    """
    all_rows = []
    for symbol in symbol_list:
        rows = analyze_exhaustion_for_symbol(symbol)
        if rows:
            all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame(), pd.DataFrame()

    raw = pd.DataFrame(all_rows)

    per_stock = raw.groupby(["symbol", "checkpoint"]).agg(
        crossed_count=("excess_days", "count"),
        avg_excess_days=("excess_days", "mean"),
        median_excess_days=("excess_days", "median"),
        avg_excess_ratio=("excess_ratio", "mean"),
        median_excess_ratio=("excess_ratio", "median"),
    ).round(2).reset_index()

    universe_rows = []
    for label in CHECKPOINTS:
        pool = raw[raw["checkpoint"] == label]["excess_ratio"]
        if pool.empty:
            continue
        universe_rows.append({
            "checkpoint": label,
            "total_crossings_pooled": len(pool),
            "instruments_contributing": raw[raw["checkpoint"] == label]["symbol"].nunique(),
            "mean_excess_ratio": round(pool.mean(), 2),
            "median_excess_ratio": round(pool.median(), 2),
            "std_excess_ratio": round(pool.std(), 2),
            "p25_excess_ratio": round(pool.quantile(0.25), 2),
            "p75_excess_ratio": round(pool.quantile(0.75), 2),
            "pct_ended_within_25pct_more": round((pool <= 0.25).mean() * 100, 1),
            "pct_ended_within_50pct_more": round((pool <= 0.50).mean() * 100, 1),
            "pct_ended_within_75pct_more": round((pool <= 0.75).mean() * 100, 1),
            "pct_ended_within_100pct_more": round((pool <= 1.00).mean() * 100, 1),
        })

    universe_summary = pd.DataFrame(universe_rows)
    return per_stock, universe_summary
