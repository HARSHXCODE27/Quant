# src/trend_1d_pipeline.py
#
# RENAMED from pledged_1d_pipeline.py (see trend_universe.py and README
# Stage 10 for the repurposing history) — batch runner for the general
# F&O trend-following 1D Supertrend screener, parallel to scale_pipeline.py
# — NOT a modification of it. Reuses fetch_data.py, supertrend.py,
# flip_analysis.py, monthly_range.py, summary_stats.py exactly as-is (all
# already interval-agnostic — they take an `interval` argument, nothing here
# required changing them).
#
# Why a SEPARATE file instead of just calling scale_pipeline.py with a
# different interval: scale_pipeline.process_stock() hardcodes
# interval="4hour" AND export_report.export_full_report() writes to a fixed
# exports/{symbol}_full_report.xlsx with no interval in the filename. Calling
# it here with 1D data would SILENTLY OVERWRITE the existing 4H credit-spread
# report for every symbol that's in both universes (most of them, now that
# the universe is the full F&O list). This file fetches interval="day" and
# writes to a separate exports/trend_1d/ folder instead — same pattern
# already used for exports/debit_spread/.

import os
import time
import traceback
from datetime import datetime
import pandas as pd

from src.fetch_data import fetch_historical_data, save_raw_data
from src.supertrend import load_raw_data, apply_supertrend
from src.flip_analysis import detect_flips
from src.monthly_range import compute_monthly_range
from src.summary_stats import compute_summary_stats

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "trend_1d")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

INTERVAL = "day"


def _export_full_report(trades_df, monthly_df, summary_df, symbol):
    """
    Same three-sheet (Flips / Monthly Range / Summary) layout as
    export_report.export_full_report — duplicated here rather than reusing
    that function directly, since it hardcodes the top-level exports/
    folder with no way to redirect it to exports/trend_1d/ without
    editing it.
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")

    trades_excel = trades_df.copy()
    trades_excel["entry_date"] = pd.to_datetime(trades_excel["entry_date"]).dt.tz_localize(None)
    trades_excel["exit_date"] = pd.to_datetime(trades_excel["exit_date"]).dt.tz_localize(None)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        trades_excel.to_excel(writer, sheet_name="Flips", index=False)
        monthly_df.to_excel(writer, sheet_name="Monthly Range", index=False)
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    print(f"Saved full report to {path}")
    return path


def already_done(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    return os.path.exists(path)


def process_instrument(symbol, token, kite, from_date, to_date):
    """
    from_date should go back far enough that the daily-timeframe flip count
    is statistically comparable to the 4H universe's — daily candles are
    ~6x coarser than 4H, so flips are proportionally rarer per calendar
    year. Kite's daily-candle history goes back much further than its
    intraday history with no extra chunking penalty (fetch_historical_data's
    ~395-day chunking still applies mechanically but costs nothing extra
    besides a few more requests) — default to a long window (years, not
    months) rather than reusing the 4H universe's shorter recent window.
    """
    df = fetch_historical_data(kite, token, from_date, to_date, interval=INTERVAL)
    if df.empty or len(df) < 50:
        raise ValueError(f"Insufficient data ({len(df)} candles)")

    save_raw_data(df, symbol, interval=INTERVAL)
    df = df.set_index("date")

    df_st = apply_supertrend(df)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(df)
    summary = compute_summary_stats(trades, monthly)
    _export_full_report(trades, monthly, summary, symbol)


def process_instrument_incremental(symbol, token, kite, to_date,
                                    deep_from_date=datetime(2015, 1, 1),
                                    quick_lookback_days=400):
    """
    REGRESSION FIX (found while building the Stage 11 trend-following
    ranking, back when the universe was still the 154-symbol pledged-
    securities list): process_instrument() always does a full replace -
    it fetches exactly [from_date, to_date] and save_raw_data() overwrites
    the raw CSV wholesale. Notebook 12's live screener was calling
    run_all_instruments(..., force_refresh=True) across the FULL universe
    on every run, using a short ~390-day window for rate-limit safety -
    which meant every routine live check was silently replacing the deep
    multi-year history notebook 10 built with just that short window. After
    repeated runs, every symbol's saved history had collapsed to ~1 year,
    taking UP-closed-flip counts per symbol down to 1-8 (nowhere near the
    >=15 floor used everywhere else in this project) - discovered when
    score_for_trend_following() came up empty.

    This function EXTENDS instead of replacing: if raw data already exists
    for the symbol, it only fetches the recent window needed to catch up
    (quick_lookback_days, still short and rate-limit-safe - same number
    notebook 13 already used), then MERGES the new candles onto the
    existing saved history (dedup on date, sorted) before recomputing
    flips/summary on the FULL merged history. Only does a genuine deep
    fetch (deep_from_date) the first time a symbol has no saved data at
    all. Use this for the live screener's full-universe refresh instead of
    process_instrument() - process_instrument() itself is left unchanged
    and is still the right choice for notebook 10's deliberate deep
    monthly refresh, where a full fetch from deep_from_date is the actual
    intent, not a bug.
    """
    try:
        existing = load_raw_data(symbol, interval=INTERVAL)
    except FileNotFoundError:
        existing = None

    if existing is None or existing.empty:
        fetch_from = deep_from_date
    else:
        last_saved = pd.Timestamp(existing.index.max()).tz_localize(None)
        fetch_from = (last_saved - pd.Timedelta(days=min(quick_lookback_days, 400))).to_pydatetime()

    new_df = fetch_historical_data(kite, token, fetch_from, to_date, interval=INTERVAL)
    if new_df.empty:
        raise ValueError("No data returned from fetch")

    def _to_naive(series):
        series = pd.to_datetime(series)
        return series.dt.tz_localize(None) if series.dt.tz is not None else series

    new_df["date"] = _to_naive(new_df["date"])

    if existing is not None and not existing.empty:
        existing_reset = existing.reset_index()
        existing_reset["date"] = _to_naive(existing_reset["date"])
        combined = pd.concat([existing_reset, new_df], ignore_index=True)
        # keep="last" is load-bearing. existing data is concatenated FIRST, and
        # drop_duplicates defaults to keep="first" — so the SAVED candle used to
        # win over the freshly fetched one. Any candle saved while its 4H/1D
        # window was still forming (i.e. any run during market hours) was frozen
        # as a partial bar forever, because no later refresh could overwrite it.
        # Real damage: ULTRACEMCO kept a flat 11815 bar on 29 shares of volume
        # for 2026-08-11 13:15, and 29 of 48 refreshed symbols held candles at
        # <10% of their normal volume — corrupt bars feeding Supertrend, so wrong
        # flips, wrong trend ages and wrong signals. Fresh data must win.
        combined = combined.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)

        # SAFETY GUARD (added after a second, real occurrence of the exact
        # regression this function was built to fix — some symbols'
        # multi-year history silently shrank back to ~400 days again even
        # with this incremental function in place, root cause not fully
        # pinned down). A correct incremental merge can only ever grow or
        # hold steady in earliest-date coverage, never shrink it. If it
        # would shrink, something upstream went wrong (existing wasn't
        # read/merged correctly) — refuse to save and fail loudly instead
        # of silently overwriting good history with a short window.
        existing_earliest = existing_reset["date"].min()
        combined_earliest = combined["date"].min()
        if pd.notna(existing_earliest) and combined_earliest > existing_earliest + pd.Timedelta(days=5):
            raise ValueError(
                f"{symbol}: incremental merge would SHRINK saved history "
                f"(existing started {existing_earliest.date()}, merge result "
                f"would start {combined_earliest.date()}) — refusing to save. "
                f"Re-run notebook 10 (deep refresh) for this symbol instead."
            )
    else:
        combined = new_df.sort_values("date").reset_index(drop=True)

    save_raw_data(combined, symbol, interval=INTERVAL)  # saves the FULL merged history, not just the new slice
    combined_indexed = combined.set_index("date")

    if len(combined_indexed) < 50:
        raise ValueError(f"Insufficient data ({len(combined_indexed)} candles)")

    df_st = apply_supertrend(combined_indexed)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(combined_indexed)
    summary = compute_summary_stats(trades, monthly)
    _export_full_report(trades, monthly, summary, symbol)


def run_all_instruments(kite, token_lookup, symbol_list, from_date, to_date,
                         delay_seconds=0.4, force_refresh=False, incremental=False):
    """
    incremental=False (default, unchanged behavior): uses process_instrument()
    - a genuine full replace/fetch, correct for notebook 10's deliberate
    deep refresh.

    incremental=True: uses process_instrument_incremental() instead - for
    notebook 13's live screener, so routine checks extend saved history
    rather than replacing it. `from_date` is ignored in this mode (the
    incremental function derives its own fetch window from what's already
    saved); `to_date` is still used.
    """
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_path = os.path.join(LOGS_DIR, "trend_1d_scale_run_log.csv")

    results = []
    total = len(symbol_list)

    for i, symbol in enumerate(symbol_list, start=1):
        if already_done(symbol) and not force_refresh and not incremental:
            print(f"[{i}/{total}] {symbol} — already done, skipping")
            results.append({"symbol": symbol, "status": "SKIPPED_ALREADY_DONE", "error": ""})
            continue

        token = token_lookup.get(symbol)
        if token is None:
            print(f"[{i}/{total}] {symbol} — no NSE token found, skipping")
            results.append({"symbol": symbol, "status": "FAILED", "error": "No NSE instrument token found"})
            continue

        try:
            print(f"[{i}/{total}] {symbol} — processing...")
            if incremental:
                process_instrument_incremental(symbol, token, kite, to_date)
            else:
                process_instrument(symbol, token, kite, from_date, to_date)
            results.append({"symbol": symbol, "status": "SUCCESS", "error": ""})
            print(f"[{i}/{total}] {symbol} — done")
        except Exception as e:
            error_msg = str(e)
            print(f"[{i}/{total}] {symbol} — FAILED: {error_msg}")
            results.append({"symbol": symbol, "status": "FAILED", "error": error_msg})
            with open(os.path.join(LOGS_DIR, "trend_1d_error_details.log"), "a") as f:
                f.write(f"\n--- {symbol} at {datetime.now()} ---\n")
                f.write(traceback.format_exc())

        time.sleep(delay_seconds)
        pd.DataFrame(results).to_csv(log_path, index=False)

    results_df = pd.DataFrame(results)
    succeeded = int((results_df["status"] == "SUCCESS").sum()) if "status" in results_df else 0
    print(f"\nDone. {succeeded}/{total} succeeded.")
    return results_df


def reprocess_instrument(symbol):
    """Recompute-only refresh (no API call) - reuses already-saved raw 1D data."""
    df = load_raw_data(symbol, interval=INTERVAL)
    df_st = apply_supertrend(df)
    trades = detect_flips(df_st)
    monthly = compute_monthly_range(df)
    summary = compute_summary_stats(trades, monthly)
    _export_full_report(trades, monthly, summary, symbol)


def reprocess_all(symbol_list):
    total = len(symbol_list)
    for i, symbol in enumerate(symbol_list, start=1):
        try:
            reprocess_instrument(symbol)
            print(f"[{i}/{total}] {symbol} — updated")
        except Exception as e:
            print(f"[{i}/{total}] {symbol} — FAILED: {e}")
