# src/strategy_scoring.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def _pct_rank(series, lower_is_better):
    """Shared helper: converts a raw metric into a 0-100 percentile rank across all stocks."""
    ranks = series.rank(pct=True) * 100
    return (100 - ranks) if lower_is_better else ranks

def _add_volatility_persistence_flag(df, threshold_percentile="90th percentile monthly range_pct"):
    """
    Checks each stock's most recently CLOSED month's range against its own
    percentile — flags stocks whose last month was an outlier, since tested
    evidence shows wide months tend to be followed by continued elevated
    volatility (momentum), not reversion. See README for the underlying test.
    """
    import pandas as pd
    from datetime import datetime

    current_year_month = datetime.now().strftime("%Y-%m")
    flags = []

    for symbol in df["symbol"]:
        path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            flags.append({"symbol": symbol, "last_month_range_pct": None, "volatility_persistence_flag": ""})
            continue

        try:
            monthly = pd.read_excel(path, sheet_name="Monthly Range")
            closed_months = monthly[monthly["year_month"] != current_year_month]
            if closed_months.empty:
                flags.append({"symbol": symbol, "last_month_range_pct": None, "volatility_persistence_flag": ""})
                continue

            last_month = closed_months.iloc[-1]
            p90 = monthly["range_pct"].quantile(0.90)

            is_outlier = last_month["range_pct"] > p90
            flag_text = "⚠ ELEVATED — last month was an outlier, momentum data suggests caution" if is_outlier else ""

            flags.append({
                "symbol": symbol,
                "last_month_range_pct": round(last_month["range_pct"], 2),
                "volatility_persistence_flag": flag_text
            })
        except Exception:
            flags.append({"symbol": symbol, "last_month_range_pct": None, "volatility_persistence_flag": ""})

    flags_df = pd.DataFrame(flags)
    return df.merge(flags_df, on="symbol", how="left")

def _add_trend_age_flag(df):
    """
    Checks each stock's currently OPEN trend age against its own historical
    duration percentiles. Tested evidence (reversion_test.py) shows aged trends
    tend toward momentum/continuation, NOT reversal — so this is framed as a
    mild positive note, not a warning, unlike the short IC volatility flag.
    """
    import pandas as pd
    from datetime import datetime

    flags = []

    for symbol in df["symbol"]:
        path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            flags.append({"symbol": symbol, "current_trend_age_days": None, "trend_age_note": ""})
            continue

        try:
            trades = pd.read_excel(path, sheet_name="Flips")
            open_trade = trades[trades["status"] == "OPEN"]
            if open_trade.empty:
                flags.append({"symbol": symbol, "current_trend_age_days": None, "trend_age_note": ""})
                continue
            open_trade = open_trade.iloc[0]

            entry_date = pd.to_datetime(open_trade["entry_date"]).tz_localize(None)
            age_days = (datetime.now() - entry_date).days

            summary = pd.read_excel(path, sheet_name="Summary")
            def get_metric(name):
                row = summary[summary["metric"] == name]
                return row["value"].values[0] if not row.empty else None

            p75_dur = get_metric("75th percentile duration (days)")

            note = ""
            if p75_dur and age_days > p75_dur:
                note = "note: aged trend — tested data shows momentum, not reversal risk"

            flags.append({
                "symbol": symbol,
                "current_trend_age_days": age_days,
                "trend_age_note": note
            })
        except Exception:
            flags.append({"symbol": symbol, "current_trend_age_days": None, "trend_age_note": ""})

    flags_df = pd.DataFrame(flags)
    return df.merge(flags_df, on="symbol", how="left")

def score_for_credit_spreads(comparison_df, min_flips=30, gap_risk_threshold=5.0):
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    df["_score_adverse_median"]  = _pct_rank(df["Median max_adverse_pct"], lower_is_better=True)
    df["_score_within_month"]    = _pct_rank(df["% completed within a monthly cycle"], lower_is_better=True)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=False)
    df["_score_adverse_worst"]   = _pct_rank(df["Worst max_adverse_pct (4yr)"], lower_is_better=True)
    df["_score_gap_worst"]       = _pct_rank(df["Worst single gap (4yr)"], lower_is_better=True)

    df["credit_spread_score"] = (
        df["_score_adverse_median"]  * 3 +
        df["_score_within_month"]    * 3 +
        df["_score_duration_median"] * 3 +
        df["_score_adverse_worst"]   * 2 +
        df["_score_gap_worst"]       * 2
    ) / 13
    df["credit_spread_score"] = df["credit_spread_score"].round(1)

    # Flag — doesn't affect the score or exclude the stock, just a visible warning
    df["gap_risk_flag"] = df["Worst single gap (4yr)"].apply(
        lambda x: f"⚠ HIGH GAP RISK (>{gap_risk_threshold}%)" if x > gap_risk_threshold else ""
    )

    result_cols = ["symbol", "credit_spread_score", "gap_risk_flag", "Total flips (closed)",
                    "Median duration (days)", "% completed within a monthly cycle",
                    "Median max_adverse_pct", "Worst max_adverse_pct (4yr)",
                    "Worst single gap (4yr)"]

    result = df[result_cols].sort_values("credit_spread_score", ascending=False).reset_index(drop=True)
    result = _add_trend_age_flag(result)
    return result

def score_for_short_iron_condor(comparison_df, min_flips=30, gap_risk_threshold=4.0):
    """
    Ranks stocks for short iron condor suitability — favors stocks that stay
    range-bound, with tight monthly swings and quick-reverting trends.
    """
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    df["_score_range_median"]    = _pct_rank(df["Median monthly range_pct"], lower_is_better=True)
    df["_score_adverse_median"]  = _pct_rank(df["Median max_adverse_pct"], lower_is_better=True)
    df["_score_range_worst"]     = _pct_rank(df["Largest monthly range_pct"], lower_is_better=True)
    df["_score_adverse_worst"]   = _pct_rank(df["Worst max_adverse_pct (4yr)"], lower_is_better=True)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=True)  # flipped vs credit spreads

    df["short_ic_score"] = (
        df["_score_range_median"]    * 3 +
        df["_score_adverse_median"]  * 3 +
        df["_score_range_worst"]     * 3 +
        df["_score_adverse_worst"]   * 2 +
        df["_score_duration_median"] * 2
    ) / 13
    df["short_ic_score"] = df["short_ic_score"].round(1)

    df["gap_risk_flag"] = df["Worst single gap (4yr)"].apply(
        lambda x: f"⚠ HIGH GAP RISK (>{gap_risk_threshold}%)" if x > gap_risk_threshold else ""
    )

    result_cols = ["symbol", "short_ic_score", "gap_risk_flag", "Total flips (closed)",
                    "Median monthly range_pct", "Largest monthly range_pct",
                    "Median max_adverse_pct", "Worst max_adverse_pct (4yr)",
                    "Median duration (days)", "Worst single gap (4yr)"]

    result = df[result_cols].sort_values("short_ic_score", ascending=False).reset_index(drop=True)
    result = _add_volatility_persistence_flag(result)
    return result

def score_for_debit_spread(comparison_df, min_trades=30, skew_gap_threshold=0.3):
    """
    Ranks stocks/indices for debit spread suitability (Stage 9), reading the
    full-universe backtest from debit_spread_scale_pipeline.py -
    exports/DEBIT_SPREAD_COMPARISON.xlsx, NOT the Supertrend-based
    ALL_STOCKS_COMPARISON.xlsx the other four scorers use (different signal,
    different exit logic entirely - target/stop/time, not "hold until flip").

    Full-universe result (214 instruments, Nov 2024-Aug 2026, ema_adx_signal +
    debit_spread_trades defaults): 59.3% of instruments showed a positive
    avg_r_achieved, but with high variance (std 0.21 vs mean 0.08) - this
    strategy is NOT uniformly good across instruments. That's exactly why
    this ranking exists, same reasoning as the other three scorers.

    median_r_achieved is weighted highest, not avg_r_achieved - same
    median-over-mean preference already established elsewhere in this
    project ("median preferred... data is outlier-skewed" in the assumptions
    log). A stock can have a healthy avg_r_achieved carried by a couple of
    big TARGET/TIME wins while the *typical* trade still loses - median
    catches that, average alone would miss it. This is exactly what BHARTIARTL
    showed in validation: avg 0.11R but median -0.45R.

    Returns (ranked, watchlist):
    - ranked: scored/sorted instruments with >= min_trades closed trades -
      the percentile ranking is only computed within this reliable group.
    - watchlist: instruments below min_trades, NOT blended into the same
      percentile ranking (a thin sample carries the same real uncertainty
      whether it's thin because of bad luck or because the stock was only
      recently added to F&O - e.g. SWIGGY, ~29 trades even over the full
      backtest window, purely because it hasn't been listed long enough to
      generate more signals yet). Shown separately, sorted by avg_r_achieved,
      so a promising-but-unproven name doesn't just silently disappear.
      Re-check these at the next periodic refresh - trade count grows on its
      own as more calendar time passes, no action needed to "fix" it.
    """
    df = comparison_df[comparison_df["closed_trades"] >= min_trades].copy()

    watchlist_cols = ["symbol", "closed_trades", "win_rate_pct", "avg_r_achieved",
                      "median_r_achieved", "median_candles_held"]
    watchlist = comparison_df[comparison_df["closed_trades"] < min_trades].copy()
    watchlist = watchlist[[c for c in watchlist_cols if c in watchlist.columns]]
    watchlist = watchlist.sort_values("avg_r_achieved", ascending=False).reset_index(drop=True)

    df["_score_median_r"] = _pct_rank(df["median_r_achieved"], lower_is_better=False)
    df["_score_win_rate"] = _pct_rank(df["win_rate_pct"], lower_is_better=False)
    df["_score_avg_r"]    = _pct_rank(df["avg_r_achieved"], lower_is_better=False)
    df["_score_candles"]  = _pct_rank(df["median_candles_held"], lower_is_better=True)  # faster-resolving = less theta exposure

    df["debit_spread_score"] = (
        df["_score_median_r"] * 4 +
        df["_score_win_rate"] * 3 +
        df["_score_avg_r"]    * 2 +
        df["_score_candles"]  * 1
    ) / 10
    df["debit_spread_score"] = df["debit_spread_score"].round(1)

    # Flag - doesn't affect the score or exclude the stock, just a visible
    # warning: a big gap between avg and median R means the edge leans on a
    # few outlier wins rather than a broadly reliable one - the typical trade
    # on that stock may still lose even though its average looks fine.
    skew_gap = df["avg_r_achieved"] - df["median_r_achieved"]
    df["outlier_reliance_flag"] = skew_gap.apply(
        lambda x: f"⚠ RELIES ON OUTLIER WINS (avg-median gap {x:.2f}R)" if x > skew_gap_threshold else ""
    )

    result_cols = ["symbol", "debit_spread_score", "outlier_reliance_flag",
                   "closed_trades", "win_rate_pct", "avg_r_achieved",
                   "median_r_achieved", "median_candles_held"]

    ranked = df[result_cols].sort_values("debit_spread_score", ascending=False).reset_index(drop=True)
    return ranked, watchlist

def save_ranking(ranked_df, filename):
    path = os.path.join(EXPORTS_DIR, filename)
    ranked_df.to_excel(path, sheet_name="Ranked", index=False)
    print(f"Saved ranking to {path}")
    return path