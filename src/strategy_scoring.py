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

def score_for_long_iron_condor(comparison_df, min_flips=30, gap_benefit_threshold=4.0):
    """
    Ranks stocks for long iron condor suitability — favors high-volatility,
    trend-committed stocks where big moves (which you're positioned to profit from)
    are common. Inverse priorities of short IC.
    """
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    df["_score_range_median"]    = _pct_rank(df["Median monthly range_pct"], lower_is_better=False)
    df["_score_adverse_worst"]   = _pct_rank(df["Worst max_adverse_pct (4yr)"], lower_is_better=False)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=False)
    df["_score_range_worst"]     = _pct_rank(df["Largest monthly range_pct"], lower_is_better=False)
    df["_score_adverse_median"]  = _pct_rank(df["Median max_adverse_pct"], lower_is_better=False)

    df["long_ic_score"] = (
        df["_score_range_median"]    * 3 +
        df["_score_adverse_worst"]   * 3 +
        df["_score_duration_median"] * 3 +
        df["_score_range_worst"]     * 2 +
        df["_score_adverse_median"]  * 2
    ) / 13
    df["long_ic_score"] = df["long_ic_score"].round(1)

    # For long IC, a history of big gaps is a POSITIVE signal, not a warning
    df["gap_benefit_flag"] = df["Worst single gap (4yr)"].apply(
        lambda x: f"✓ Historical gap potential (>{gap_benefit_threshold}%)" if x > gap_benefit_threshold else ""
    )

    result_cols = ["symbol", "long_ic_score", "gap_benefit_flag", "Total flips (closed)",
                    "Median monthly range_pct", "Largest monthly range_pct",
                    "Median max_adverse_pct", "Worst max_adverse_pct (4yr)",
                    "Median duration (days)", "Worst single gap (4yr)"]

    result = df[result_cols].sort_values("long_ic_score", ascending=False).reset_index(drop=True)
    result = _add_trend_age_flag(result)
    return result

def score_for_directional_buying(comparison_df, min_flips=30, liquid_universe=None):
    """
    Ranks stocks for directional option buying (long calls/puts on Supertrend
    flips) — favors stocks with strong average moves and reasonable win rates,
    restricted to a liquid universe since option buying needs tradeable near-the-
    money strikes, unlike premium-selling strategies which can tolerate thinner names.
    """
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    if liquid_universe is not None:
        df = df[df["symbol"].isin(liquid_universe)].copy()

    df["_score_pct_move"]        = _pct_rank(df["Avg pct_move (all)"], lower_is_better=False)
    df["_score_win_rate"]        = _pct_rank(df["Win rate % (pct_move > 0)"], lower_is_better=False)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=False)
    df["_score_biggest_move"]    = _pct_rank(df["Biggest single pct_move"], lower_is_better=False)

    df["directional_buy_score"] = (
        df["_score_pct_move"]        * 3 +
        df["_score_win_rate"]        * 3 +
        df["_score_duration_median"] * 2 +
        df["_score_biggest_move"]    * 2
    ) / 10
    df["directional_buy_score"] = df["directional_buy_score"].round(1)

    result_cols = ["symbol", "directional_buy_score", "Total flips (closed)",
                    "Avg pct_move (all)", "Win rate % (pct_move > 0)",
                    "Median duration (days)", "Biggest single pct_move"]

    return df[result_cols].sort_values("directional_buy_score", ascending=False).reset_index(drop=True)

def save_ranking(ranked_df, filename):
    path = os.path.join(EXPORTS_DIR, filename)
    ranked_df.to_excel(path, sheet_name="Ranked", index=False)
    print(f"Saved ranking to {path}")
    return path