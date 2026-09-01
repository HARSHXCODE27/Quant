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

DAY_MOVE_METRIC = "Worst single-day move against (4yr)"


def score_for_credit_spreads(comparison_df, min_flips=30, gap_risk_threshold=5.0,
                                day_risk_threshold=7.0):
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    df["_score_adverse_median"]  = _pct_rank(df["Median max_adverse_pct"], lower_is_better=True)
    df["_score_within_month"]    = _pct_rank(df["% completed within a monthly cycle"], lower_is_better=True)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=False)
    df["_score_adverse_worst"]   = _pct_rank(df["Worst max_adverse_pct (4yr)"], lower_is_better=True)
    df["_score_gap_worst"]       = _pct_rank(df["Worst single gap (4yr)"], lower_is_better=True)

    # Single-day move risk, weighted the same as the two other tail-risk
    # components. Added because the existing gap term only sees the overnight
    # jump: PIIND's near-record 8.97% one-day fall registered as a 1.28% gap
    # and so was invisible to every term above. Only scored when the metric
    # is present — reports built before flip_analysis.py started recording
    # worst_day_against_pct fall back to the original 13-weight formula
    # rather than silently scoring a missing column as zero.
    has_day_metric = DAY_MOVE_METRIC in df.columns and df[DAY_MOVE_METRIC].notna().any()

    weighted = (
        df["_score_adverse_median"]  * 3 +
        df["_score_within_month"]    * 3 +
        df["_score_duration_median"] * 3 +
        df["_score_adverse_worst"]   * 2 +
        df["_score_gap_worst"]       * 2
    )
    total_weight = 13

    if has_day_metric:
        df["_score_day_worst"] = _pct_rank(df[DAY_MOVE_METRIC], lower_is_better=True)
        # Per-ROW weight, not a single constant. The metric can be present for
        # most stocks and missing for a few — a report regenerated by an older
        # code path, a symbol processed by a stale cached module — and with a
        # flat denominator every one of those rows silently scores NaN and
        # disappears from the ranking entirely. That failure is invisible:
        # the ranking still looks complete, just shorter, and the missing
        # names are gone rather than flagged. Scoring each row against the
        # weights it actually has keeps them ranked on their remaining five
        # components instead.
        has_row = df["_score_day_worst"].notna()
        weighted = weighted + (df["_score_day_worst"] * 2).fillna(0)
        total_weight = pd.Series(13, index=df.index) + has_row.astype(int) * 2
        df["scored_without_day_metric"] = ~has_row

    df["credit_spread_score"] = (weighted / total_weight).round(1)

    # Flags — neither affects the score or excludes the stock, both are just
    # visible warnings, same convention as the original gap flag.
    df["gap_risk_flag"] = df["Worst single gap (4yr)"].apply(
        lambda x: f"⚠ HIGH GAP RISK (>{gap_risk_threshold}%)" if x > gap_risk_threshold else ""
    )
    if has_day_metric:
        df["day_risk_flag"] = df[DAY_MOVE_METRIC].apply(
            lambda x: f"⚠ HIGH 1-DAY MOVE RISK (>{day_risk_threshold}%)"
            if pd.notna(x) and x > day_risk_threshold else ""
        )
    else:
        df["day_risk_flag"] = ""

    result_cols = ["symbol", "credit_spread_score", "gap_risk_flag", "day_risk_flag",
                    "Total flips (closed)",
                    "Median duration (days)", "% completed within a monthly cycle",
                    "Median max_adverse_pct", "Worst max_adverse_pct (4yr)",
                    "Worst single gap (4yr)"]
    if has_day_metric:
        result_cols.append(DAY_MOVE_METRIC)

    result = df[result_cols].sort_values("credit_spread_score", ascending=False).reset_index(drop=True)
    result = _add_trend_age_flag(result)
    return result

def _weighted_median(values, weights):
    """Shared math helper: weighted median via 50% cumulative-weight cutoff."""
    import numpy as np
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = ~np.isnan(values)
    values, weights = values[mask], weights[mask]
    if len(values) == 0:
        return float("nan")
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.cumsum(w)
    cutoff = cum[-1] / 2.0
    idx = np.searchsorted(cum, cutoff)
    return float(v[min(idx, len(v) - 1)])

def _add_recency_weighted_short_ic_stats(symbol_list, halflife_months=6):
    """
    TESTED (walk-forward, 216 instruments, 9,010 symbol-month predictions):
    a recency-weighted median of monthly range_pct predicts a stock's NEXT
    month range_pct modestly better than the flat all-time median used
    elsewhere in this project - mean abs error 4.87pp -> 4.79pp at a
    6-month half-life (the best of several tried: 2/3/4/6/9/12/18 months),
    closer in ~50% of cases vs ~45% for the flat median. Real but modest -
    doesn't solve the deeper "can't confirm range-bound behavior until
    mid-month, by when premium has already decayed" problem raised by the
    user, but it's a free improvement over the flat metric with no new data
    needed, so it's added here as an additional score component alongside
    (not replacing) the existing flat metrics from ALL_STOCKS_COMPARISON.xlsx.

    Weight for a month `k` months before now: 0.5 ** (k / halflife_months) -
    a month from 6 months ago counts half as much as last month, a year ago
    a quarter as much, etc. Reads each symbol's own Monthly Range sheet for
    range_pct (the metric actually tested above), and applies the SAME
    weighting principle to max_adverse_pct from the Flips sheet (weighted by
    each closed flip's exit_date) as a consistent extension - NOT
    independently re-tested, since the tested result was specific to
    range_pct; included on the reasoning that a metric measuring "how this
    stock behaves lately" should behave consistently across both bases.
    """
    from datetime import datetime
    import pandas as pd

    now = pd.Timestamp(datetime.now())
    rows = []

    for symbol in symbol_list:
        path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            rows.append({"symbol": symbol})
            continue
        try:
            monthly = pd.read_excel(path, sheet_name="Monthly Range")
            flips = pd.read_excel(path, sheet_name="Flips")
        except Exception:
            rows.append({"symbol": symbol})
            continue

        row = {"symbol": symbol}

        if not monthly.empty:
            monthly = monthly.copy()
            monthly["month_start"] = monthly["year_month"].apply(
                lambda ym: pd.Period(ym, freq="M").start_time
            )
            months_ago = (now - monthly["month_start"]).dt.days / 30.44
            months_ago = months_ago.clip(lower=0)
            weights = 0.5 ** (months_ago / halflife_months)
            row["recency_weighted_range_pct"] = round(
                _weighted_median(monthly["range_pct"].values, weights.values), 2
            )

        closed = flips[flips["status"] == "CLOSED"].copy() if not flips.empty else flips
        if closed is not None and not closed.empty:
            closed["exit_date"] = pd.to_datetime(closed["exit_date"])
            if closed["exit_date"].dt.tz is not None:
                closed["exit_date"] = closed["exit_date"].dt.tz_localize(None)
            months_ago = (now - closed["exit_date"]).dt.days / 30.44
            months_ago = months_ago.clip(lower=0)
            weights = 0.5 ** (months_ago / halflife_months)
            row["recency_weighted_adverse_pct"] = round(
                _weighted_median(closed["max_adverse_pct"].values, weights.values), 2
            )

        rows.append(row)

    return pd.DataFrame(rows)

def score_for_short_iron_condor(comparison_df, min_flips=30, gap_risk_threshold=4.0, halflife_months=6):
    """
    Ranks stocks for short iron condor suitability — favors stocks that stay
    range-bound, with tight monthly swings and quick-reverting trends.

    Includes a recency-weighted range/adverse component alongside the flat
    all-time metrics — see _add_recency_weighted_short_ic_stats() for the
    tested justification. This does NOT solve the core timing problem this
    was built to help with (real confirmation that THIS month is holding its
    range only firms up mid-month, by when premium has already decayed) -
    that was tested directly (trend age at month-start vs realized monthly
    range_pct, correlation 0.017 across 10,671 symbol-months - no leading
    signal there) and remains unsolved; a genuine leading fix would need
    live IV-rank data, which Kite doesn't provide directly and would require
    a real Black-Scholes IV solver plus historical reconstruction - out of
    scope for this change, tracked separately.
    """
    df = comparison_df[comparison_df["Total flips (closed)"] >= min_flips].copy()

    recency = _add_recency_weighted_short_ic_stats(df["symbol"].tolist(), halflife_months=halflife_months)
    df = df.merge(recency, on="symbol", how="left")

    df["_score_range_median"]    = _pct_rank(df["Median monthly range_pct"], lower_is_better=True)
    df["_score_adverse_median"]  = _pct_rank(df["Median max_adverse_pct"], lower_is_better=True)
    df["_score_range_worst"]     = _pct_rank(df["Largest monthly range_pct"], lower_is_better=True)
    df["_score_adverse_worst"]   = _pct_rank(df["Worst max_adverse_pct (4yr)"], lower_is_better=True)
    df["_score_duration_median"] = _pct_rank(df["Median duration (days)"], lower_is_better=True)  # flipped vs credit spreads
    df["_score_range_recency"]   = _pct_rank(df["recency_weighted_range_pct"], lower_is_better=True)
    df["_score_adverse_recency"] = _pct_rank(df["recency_weighted_adverse_pct"], lower_is_better=True)

    df["short_ic_score"] = (
        df["_score_range_median"]    * 3 +
        df["_score_adverse_median"]  * 3 +
        df["_score_range_worst"]     * 3 +
        df["_score_adverse_worst"]   * 2 +
        df["_score_duration_median"] * 2 +
        df["_score_range_recency"]   * 3 +
        df["_score_adverse_recency"] * 2
    ) / 18
    df["short_ic_score"] = df["short_ic_score"].round(1)

    df["gap_risk_flag"] = df["Worst single gap (4yr)"].apply(
        lambda x: f"⚠ HIGH GAP RISK (>{gap_risk_threshold}%)" if x > gap_risk_threshold else ""
    )

    result_cols = ["symbol", "short_ic_score", "gap_risk_flag", "Total flips (closed)",
                    "Median monthly range_pct", "recency_weighted_range_pct",
                    "Largest monthly range_pct",
                    "Median max_adverse_pct", "recency_weighted_adverse_pct",
                    "Worst max_adverse_pct (4yr)",
                    "Median duration (days)", "Worst single gap (4yr)"]
    result_cols = [c for c in result_cols if c in df.columns]

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

def score_for_option_buying(comparison_df, min_trades=20, skew_gap_threshold=0.3):
    """
    Ranks stocks/indices for naked-option-buying suitability (Stage 11),
    reading exports/OPTION_BUYING_COMPARISON.xlsx (option_buying_scale_pipeline.py),
    NOT the debit spread or Supertrend comparison files - different exit
    logic (trailing stop, no fixed target) even though the entry signal is
    shared with the debit spread strategy.

    Same weighting philosophy as score_for_debit_spread, for direct
    comparability: median_r_achieved weighted highest (not avg_r_achieved) -
    a healthy average can still be a few outlier TIME/TRAIL_STOP wins
    carrying a typically-losing trade, median catches that. Same
    outlier_reliance_flag as the debit spread scorer, same threshold.

    min_trades=20 here, NOT the 30 used by score_for_debit_spread - this
    strategy now runs through apply_4h_trend_filter() (Stage 11 hard
    filter), which roughly halves signal frequency by construction (drops
    every 1H entry that disagrees with the symbol's 4H trend). After the
    filter, per-instrument closed_trades over the same window tops out
    around 27 with a mean of ~19 - a 30-trade bar would leave nothing
    ranked at all. 20 keeps a real split between "more trades, more
    trustworthy" and "thin but still real" rather than an arbitrary
    unreachable number; the >=15 floor used everywhere else in this
    project is still enforced upstream when the comparison file itself
    gets built.

    Full-universe result WITH the 4H filter (153 instruments qualified,
    same window): 70.6% positive avg_r_achieved (vs 72.5% pre-filter,
    72.5% pre-filter had more but noisier trades), mean avg R 0.198 (vs
    0.126 pre-filter), median 0.170 (vs 0.100), mean win rate 54.9% (vs
    51.1%) - the filter concentrates the edge into fewer, better-qualified
    trades. Std also widened (0.327 vs 0.224) since each instrument now has
    roughly half as many trades feeding its own average - expected, not a
    red flag; the ranking below is exactly what exists to separate the
    reliable names from the noisy ones under a thinner sample.

    Returns (ranked, watchlist) - same shape as score_for_debit_spread.
    """
    df = comparison_df[comparison_df["closed_trades"] >= min_trades].copy()

    watchlist_cols = ["symbol", "closed_trades", "win_rate_pct", "avg_r_achieved",
                      "median_r_achieved", "median_candles_held", "pct_trades_trailing_activated"]
    watchlist = comparison_df[comparison_df["closed_trades"] < min_trades].copy()
    watchlist = watchlist[[c for c in watchlist_cols if c in watchlist.columns]]
    watchlist = watchlist.sort_values("avg_r_achieved", ascending=False).reset_index(drop=True)

    df["_score_median_r"] = _pct_rank(df["median_r_achieved"], lower_is_better=False)
    df["_score_win_rate"] = _pct_rank(df["win_rate_pct"], lower_is_better=False)
    df["_score_avg_r"]    = _pct_rank(df["avg_r_achieved"], lower_is_better=False)
    df["_score_candles"]  = _pct_rank(df["median_candles_held"], lower_is_better=True)  # faster-resolving = less theta exposure

    df["option_buying_score"] = (
        df["_score_median_r"] * 4 +
        df["_score_win_rate"] * 3 +
        df["_score_avg_r"]    * 2 +
        df["_score_candles"]  * 1
    ) / 10
    df["option_buying_score"] = df["option_buying_score"].round(1)

    skew_gap = df["avg_r_achieved"] - df["median_r_achieved"]
    df["outlier_reliance_flag"] = skew_gap.apply(
        lambda x: f"⚠ RELIES ON OUTLIER WINS (avg-median gap {x:.2f}R)" if x > skew_gap_threshold else ""
    )

    result_cols = ["symbol", "option_buying_score", "outlier_reliance_flag",
                   "closed_trades", "win_rate_pct", "avg_r_achieved",
                   "median_r_achieved", "median_candles_held", "pct_trades_trailing_activated"]
    result_cols = [c for c in result_cols if c in df.columns]

    ranked = df[result_cols].sort_values("option_buying_score", ascending=False).reset_index(drop=True)
    return ranked, watchlist

def _add_trend_up_flip_stats(symbol_list, trend_exports_dir):
    """
    Reads each symbol's OWN exports/trend_1d/{symbol}_full_report.xlsx
    Flips sheet and computes stats from CLOSED UP flips only - not the
    blended UP+DOWN stats already sitting in TREND_1D_COMPARISON.xlsx.

    Why recompute rather than reuse the comparison file's columns: the
    Stage 11 strategy this ranks ("buy in uptrend, exit in downtrend on
    1D") only ever ENTERS on a UP flip - a DOWN flip's pct_move describes a
    trade nobody using this strategy takes, so blending it in would score
    instruments on trades they don't make. Also computes a real
    median_pct_move_up (not just the average already in the comparison
    file) - same median-over-mean standard used everywhere else in this
    project ("Median preferred over average throughout... data is
    outlier-skewed" in the assumptions log), and lets the ranking flag
    avg-vs-median skew the same way score_for_debit_spread/
    score_for_option_buying already do.
    """
    import os
    rows = []
    for symbol in symbol_list:
        path = os.path.join(trend_exports_dir, f"{symbol}_full_report.xlsx")
        if not os.path.exists(path):
            rows.append({"symbol": symbol, "up_closed_count": 0})
            continue
        try:
            flips = pd.read_excel(path, sheet_name="Flips")
        except Exception:
            rows.append({"symbol": symbol, "up_closed_count": 0})
            continue

        up_closed = flips[(flips["status"] == "CLOSED") & (flips["direction"] == "UP")]
        if up_closed.empty:
            rows.append({"symbol": symbol, "up_closed_count": 0})
            continue

        rows.append({
            "symbol": symbol,
            "up_closed_count": len(up_closed),
            "median_pct_move_up": round(up_closed["pct_move"].median(), 2),
            "avg_pct_move_up": round(up_closed["pct_move"].mean(), 2),
            "win_rate_up_pct": round((up_closed["pct_move"] > 0).mean() * 100, 1),
            "median_max_adverse_up": round(up_closed["max_adverse_pct"].median(), 2),
        })

    return pd.DataFrame(rows)

def score_for_trend_following(min_flips=15, gap_risk_threshold=10.0,
                                       skew_gap_threshold=3.0, fno_symbol_list=None):
    """
    Ranks the general F&O trend-following 1D universe (Stage 10/11) for the
    strategy it's actually meant to answer: buy the share itself on a fresh
    UP flip, exit on the opposite DOWN flip. Different from every other scorer
    in this project in two ways:

    1. It scores buying the UNDERLYING directly, not an options structure -
       so unlike credit spreads/short IC (which favor price staying
       CONTAINED, a premium-selling objective) or debit spread/option
       buying (defined-risk, ATR-bounded), this favors a large favorable
       move on the UP flips specifically. Built from `_add_trend_up_flip_stats()`,
       which recomputes real UP-only closed-flip stats per symbol rather
       than reusing TREND_1D_COMPARISON.xlsx's blended UP+DOWN columns.

    2. Because buying the underlying needs no F&O contract, this scores the
       FULL F&O stock+index universe (see trend_universe.py) rather than
       being gated by any tradability filter.

    REPURPOSED (see trend_universe.py, README Stage 10): originally
    ranked a 154-symbol pledged-securities universe with Shares and ETFs
    scored SEPARATELY (two groups, own percentile scales each), since ETFs
    structurally have smaller typical moves than individual stocks and a
    blended rank made every ETF look permanently worse for reasons that had
    nothing to do with quality. The universe is now pure F&O stocks+indices —
    no ETFs — so that split is gone; `security_type` ("Stock"/"Index") is
    still carried through purely as a display/filter column, not a
    re-split scoring axis (an index behaves like a large stable stock, not
    a thin sector ETF, so there's no reason to score it on a separate scale).

    No stop-loss-capped scoring here: src/stop_loss_test.py found no
    candidate stop rule beats holding to the natural DOWN-flip exit (every
    rule's stopped-out flips would have averaged a POSITIVE outcome if held)
    — so this scores the actual strategy (hold to DOWN flip), not a
    hypothetical stopped-out version of it.

    gap_risk_threshold=10.0, NOT the 5.0 inherited from the 4H credit-spread
    scorer at first: checked the real "Worst single gap (4yr)" distribution
    across all 140 processed instruments (median 6.94%, mean 8.3%) and found
    5% flagged 94 of 96 ranked instruments - basically everyone, which
    defeats the point of a flag (it should separate candidates, not fire
    universally). 10% sits right at the natural break between the 80th
    percentile (~10%) and 85th (~13.1%), flagging roughly the top-quintile
    gap-prone names (17.9% of the universe) instead of nearly all of it.
    5% made sense for the 4H strategies' shorter, faster-resolving trades;
    1D positions are held for weeks-to-months, long enough that almost any
    stock will show one >5% single-day move somewhere in a multi-year
    history without that being unusually risky. Re-checked after the Stage
    10 universe swap to the full 216-instrument F&O universe: 10% still
    flags 14.4% of instruments, in the same "meaningful minority, not
    everyone" range — no change needed.

    Weights: median_pct_move_up highest (the actual expected gain when the
    trade works - the real point of a directional buy-hold), win_rate_up
    next, median_max_adverse_up penalized (drawdown pain during the hold -
    matters more here than for an options trade, since there's no defined
    max loss). No target/candles-held component - unlike options, holding
    a share/ETF costs no theta, so speed-of-resolution isn't a real cost.

    **Consistency (skew_gap = avg_pct_move_up - median_pct_move_up) is its
    own weighted component, not just a cosmetic flag.** Originally
    `outlier_reliance_flag` was purely a label sitting next to a score that
    never actually reflected it - a stock whose average was inflated by a
    handful of lucky wins could still out-score a more consistent one on
    raw median/win-rate/adverse numbers alone. Real example that surfaced
    this: BAJAJFINSV (avg 12.49%, median only 3.96%, gap 8.53pp) scored
    HIGHER than TATASTEEL (avg 9.68%, median 3.76%, gap 5.92pp) under the
    old formula, despite BAJAJFINSV's median being barely better and its
    gap being meaningfully worse - the flashy average was doing the
    talking, and the flag next to it wasn't actually changing anything. Now
    skew_gap is percentile-ranked (lower gap = better) and weighted into
    the score directly, so a wide gap actually costs points instead of
    just being noted alongside an unaffected number.

    min_flips filters on UP-closed-flip count specifically (not total
    flips) - a symbol with 20 total flips but only 4 of them UP-and-closed
    doesn't have a trustworthy median_pct_move_up. Same >=15 floor used
    everywhere else in this project.

    Returns (ranked, watchlist) - ranked is one table across the whole
    universe (security_type retained as a display column only); watchlist
    is everything below min_flips, sorted by avg_pct_move_up.
    """
    from src.trend_universe import load_trend_universe

    trend_exports_dir = os.path.join(PROJECT_ROOT, "exports", "trend_1d")
    comparison_path = os.path.join(EXPORTS_DIR, "TREND_1D_COMPARISON.xlsx")
    comparison = pd.read_excel(comparison_path)

    universe = load_trend_universe(fno_symbol_list=fno_symbol_list)[["symbol", "security_type"]]

    up_stats = _add_trend_up_flip_stats(comparison["symbol"].tolist(), trend_exports_dir)

    merged = comparison[["symbol", "Worst single gap (4yr)"]].merge(up_stats, on="symbol", how="left")
    merged = merged.merge(universe, on="symbol", how="left")
    merged["up_closed_count"] = merged["up_closed_count"].fillna(0)

    qualified = merged[merged["up_closed_count"] >= min_flips].copy()

    watchlist_cols = ["symbol", "security_type", "up_closed_count", "win_rate_up_pct",
                       "avg_pct_move_up", "median_pct_move_up", "median_max_adverse_up"]
    watchlist = merged[merged["up_closed_count"] < min_flips].copy()
    watchlist = watchlist[[c for c in watchlist_cols if c in watchlist.columns]]
    watchlist = watchlist.sort_values("avg_pct_move_up", ascending=False).reset_index(drop=True)

    scored = qualified.copy()
    scored["_score_median_move"] = _pct_rank(scored["median_pct_move_up"], lower_is_better=False)
    scored["_score_win_rate"]    = _pct_rank(scored["win_rate_up_pct"], lower_is_better=False)
    scored["_score_adverse"]     = _pct_rank(scored["median_max_adverse_up"], lower_is_better=True)

    # Consistency component - the fix for a real problem found in this
    # project: the outlier_reliance_flag used to be purely cosmetic, a
    # label sitting next to a score that never actually reflected it. A
    # stock whose average was inflated by a few lucky wins could still
    # out-score a more consistent one on raw median/win-rate/adverse
    # numbers alone, which is misleading - a flag that doesn't move the
    # number isn't doing its job. skew_gap (avg - median pct_move_up) is
    # now its own percentile-ranked component, LOWER gap = better score
    # (a tighter gap means the median is a trustworthy estimate of what
    # actually happens; a wide gap means a few outliers are propping up
    # the average and the "real" typical outcome may be weaker than it
    # looks).
    scored["_skew_gap"] = scored["avg_pct_move_up"] - scored["median_pct_move_up"]
    scored["_score_consistency"] = _pct_rank(scored["_skew_gap"], lower_is_better=True)

    scored["trend_score"] = (
        scored["_score_median_move"]  * 4 +
        scored["_score_win_rate"]     * 3 +
        scored["_score_adverse"]      * 2 +
        scored["_score_consistency"]  * 2
    ) / 11
    scored["trend_score"] = scored["trend_score"].round(1)

    # outlier_reliance_flag still shown - now confirmatory context for what
    # the score already accounts for, not a contradiction of it.
    scored["outlier_reliance_flag"] = scored["_skew_gap"].apply(
        lambda x: f"⚠ RELIES ON OUTLIER WINS (avg-median gap {x:.2f}pp)" if x > skew_gap_threshold else ""
    )
    scored["gap_risk_flag"] = scored["Worst single gap (4yr)"].apply(
        lambda x: f"⚠ HIGH GAP RISK (>{gap_risk_threshold}%)" if pd.notna(x) and x > gap_risk_threshold else ""
    )

    result_cols = ["symbol", "security_type", "trend_score", "outlier_reliance_flag",
                   "gap_risk_flag", "up_closed_count", "win_rate_up_pct", "avg_pct_move_up",
                   "median_pct_move_up", "median_max_adverse_up"]
    result_cols = [c for c in result_cols if c in scored.columns]

    ranked = scored[result_cols].sort_values(
        "trend_score", ascending=False
    ).reset_index(drop=True)

    return ranked, watchlist

def save_ranking(ranked_df, filename):
    path = os.path.join(EXPORTS_DIR, filename)
    ranked_df.to_excel(path, sheet_name="Ranked", index=False)
    print(f"Saved ranking to {path}")
    return path