# src/stop_loss_test.py
#
# NEW test, same family as reversion_test.py/exhaustion_test.py — a
# candidate stop-loss rule is tested against real historical flip data
# BEFORE being wired into anything live, not assumed.
#
# QUESTION: the 1D trend-following strategy (Stage 10) buys a
# share/ETF on a fresh 1D Supertrend UP flip and holds until the opposite
# DOWN flip. That has no defined max loss on a single trade — the position
# can run against you for the trend's ENTIRE adverse excursion before the
# Supertrend itself finally flips. This tests whether cutting a trade early
# via a stop-loss, at various candidate thresholds, actually improves the
# outcome versus just holding to the natural DOWN-flip exit — or whether it
# mostly just cuts off trades that would have recovered and won anyway.
#
# UP-only, same as _add_trend_up_flip_stats() in strategy_scoring.py: this
# strategy never takes a DOWN-flip trade, so DOWN flips are irrelevant here
# and excluded entirely, not just de-weighted.
#
# METHOD — three candidate rule families, using columns flip_analysis.py
# ALREADY computes and writes to the Flips sheet, no new backtest engine:
#
#   1. Fixed-%: a flip "would have stopped" if max_adverse_pct (the flip's
#      own worst adverse excursion, already computed) exceeds a flat
#      threshold. Same threshold for every stock regardless of how volatile
#      it normally is.
#   2. ATR-multiple: same test, but the threshold is PER-FLIP — entry-date
#      ATR (computed here from data/raw/{symbol}_day.csv via the exact same
#      apply_atr() already used by option_buying_trades.py, not
#      reimplemented) times a multiplier, expressed as a % of entry price so
#      it's comparable to max_adverse_pct. Volatility-adaptive instead of one
#      flat number across very different stocks.
#   3. worst_day_against_pct-based: tested as its OWN trigger basis, not
#      just another threshold on the same metric. max_adverse_pct is a
#      cumulative/path measure; worst_day_against_pct is a single
#      close-to-close day. This project's own PIIND finding (Stage 8d) is
#      that a single bad day can matter more than the path getting there —
#      this checks whether a day-based trigger flags flips the path-based
#      rules miss entirely.
#
# For a "stopped" flip, the capped outcome is assumed to be exactly
# -threshold%. For a flip that never breaches the threshold, the outcome is
# unchanged (the actual pct_move).
#
# CAVEAT (state plainly, don't bury it): this assumes the stop FILLS at
# exactly -threshold% once max_adverse_pct/worst_day_against_pct crosses it.
# A real stop can be gapped through in one session and fill worse — this is
# a first-pass test using the aggregate per-flip stats already on hand, the
# same standard as reversion_test.py/exhaustion_test.py's existing lookback
# methodology, NOT a claim of realistic fill simulation. A follow-up that
# walks the actual daily price path for just the flips that would trigger
# (to measure real slippage) is a reasonable Phase 2, not done here.
#
# This script REPORTS the comparison; it does not auto-pick a rule. Which
# threshold to adopt (if any) is a judgment call from the summary table.

import os
import pandas as pd
import pandas_ta as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "trend_1d")
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

MIN_CLOSED_FLIPS = 15  # same floor as reversion_test.py/exhaustion_test.py

FIXED_PCTS = (5.0, 8.0, 10.0, 12.0)
ATR_MULTS = (1.5, 2.0, 2.5)
WORST_DAY_PCTS = (5.0, 8.0, 10.0, 12.0)
ATR_PERIOD = 14


def _atr_at_entry_lookup(symbol, atr_period=ATR_PERIOD):
    """
    ATR isn't in the Flips sheet — apply_supertrend() (src/supertrend.py)
    only exposes pandas_ta.supertrend()'s SUPERT_*/SUPERTd_*/SUPERTl_*/
    SUPERTs_* columns, no ATR column, even though ATR is computed
    internally by the library. Recomputed here directly from the saved raw
    1D candles using the exact same call as
    option_buying_trades.py::apply_atr() — not reimplemented differently.

    Returns a Series indexed by date, or None if the raw file is missing.
    """
    path = os.path.join(RAW_DIR, f"{symbol}_day.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    df[f"ATR_{atr_period}"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=atr_period)
    return df.set_index("date")[f"ATR_{atr_period}"]


def collect_up_flips_for_symbol(symbol, atr_period=ATR_PERIOD):
    """
    Per-stock pass: returns a list of per-flip records (raw, not
    aggregated) for every CLOSED UP flip, or None if the symbol has fewer
    than MIN_CLOSED_FLIPS such flips or its report/raw data is missing.

    Each record carries what every candidate rule needs: pct_move (actual
    outcome held to the natural DOWN-flip exit), max_adverse_pct,
    worst_day_against_pct, and atr_at_entry_pct (ATR at entry_date,
    expressed as a % of entry_price — comparable to the other two, and
    already put into per-flip terms so run_sl_test() never needs to look at
    raw data again).
    """
    report_path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(report_path):
        return None

    flips = pd.read_excel(report_path, sheet_name="Flips")
    up_closed = flips[(flips["status"] == "CLOSED") & (flips["direction"] == "UP")].copy()
    if len(up_closed) < MIN_CLOSED_FLIPS:
        return None

    if "worst_day_against_pct" not in up_closed.columns:
        up_closed["worst_day_against_pct"] = pd.NA

    atr_series = _atr_at_entry_lookup(symbol, atr_period)

    rows = []
    for _, r in up_closed.iterrows():
        entry_date = pd.to_datetime(r["entry_date"])
        atr_at_entry_pct = None
        if atr_series is not None:
            eligible = atr_series[atr_series.index <= entry_date]
            if not eligible.empty and pd.notna(eligible.iloc[-1]) and r["entry_price"]:
                atr_at_entry_pct = round(float(eligible.iloc[-1]) / float(r["entry_price"]) * 100, 3)

        rows.append({
            "symbol": symbol,
            "entry_date": entry_date,
            "pct_move": r["pct_move"],
            "max_adverse_pct": r["max_adverse_pct"],
            "worst_day_against_pct": r["worst_day_against_pct"],
            "atr_at_entry_pct": atr_at_entry_pct,
        })
    return rows


def _rule_outcome(pool, trigger_col, threshold_series):
    """
    Applies one candidate rule against the pooled per-flip DataFrame.
    threshold_series can be a flat float (fixed-%/worst-day rules) or a
    per-row Series (ATR-multiple rule, since the threshold varies by flip).

    Returns a dict of summary stats for this rule, plus the row-level
    'stopped'/'capped_outcome' Series so callers needing the stopped-only
    comparison (capped vs actual) can reuse them without recomputing.
    """
    stopped = pool[trigger_col] > threshold_series
    capped_outcome = pool["pct_move"].where(~stopped, -threshold_series)

    n = len(pool)
    n_stopped = int(stopped.sum())
    stopped_actual = pool.loc[stopped, "pct_move"]
    stopped_capped = capped_outcome[stopped]

    return {
        "n_flips": n,
        "pct_stopped_out": round(n_stopped / n * 100, 1) if n else None,
        "mean_pct_move": round(capped_outcome.mean(), 2),
        "median_pct_move": round(capped_outcome.median(), 2),
        "win_rate": round((capped_outcome > 0).mean() * 100, 1),
        "mean_capped_loss_when_stopped": round(stopped_capped.mean(), 2) if n_stopped else None,
        "mean_actual_pct_move_when_stopped": round(stopped_actual.mean(), 2) if n_stopped else None,
    }


def run_sl_test(symbol_list, fixed_pcts=FIXED_PCTS, atr_mults=ATR_MULTS,
                 worst_day_pcts=WORST_DAY_PCTS, atr_period=ATR_PERIOD):
    """
    Runs collect_up_flips_for_symbol() across the universe and returns
    (per_stock_summary, universe_summary):

    - per_stock_summary: one row per stock (n_flips, no-SL mean/median
      pct_move, win_rate) — reference only, for spot-checking an individual
      stock, NOT what the verdict is based on.

    - universe_summary: one row per candidate rule (a 'no_SL' baseline row
      first, using raw pct_move unmodified), pooling every qualifying UP-
      closed flip across the whole universe. THIS table is what deciding
      whether/which SL rule to adopt should be read from.
    """
    all_rows = []
    for symbol in symbol_list:
        rows = collect_up_flips_for_symbol(symbol, atr_period)
        if rows:
            all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame(), pd.DataFrame()

    pool = pd.DataFrame(all_rows)

    per_stock = pool.groupby("symbol").agg(
        n_flips=("pct_move", "count"),
        mean_pct_move=("pct_move", "mean"),
        median_pct_move=("pct_move", "median"),
    ).round(2).reset_index()
    per_stock["win_rate"] = pool.groupby("symbol")["pct_move"].apply(lambda s: round((s > 0).mean() * 100, 1)).values

    universe_rows = []

    baseline = {
        "rule": "no_SL",
        "n_flips": len(pool),
        "pct_stopped_out": 0.0,
        "mean_pct_move": round(pool["pct_move"].mean(), 2),
        "median_pct_move": round(pool["pct_move"].median(), 2),
        "win_rate": round((pool["pct_move"] > 0).mean() * 100, 1),
        "mean_capped_loss_when_stopped": None,
        "mean_actual_pct_move_when_stopped": None,
    }
    universe_rows.append(baseline)

    for pct in fixed_pcts:
        out = _rule_outcome(pool, "max_adverse_pct", pct)
        out["rule"] = f"fixed_{pct:g}pct"
        universe_rows.append(out)

    atr_pool = pool.dropna(subset=["atr_at_entry_pct"])
    for mult in atr_mults:
        threshold = atr_pool["atr_at_entry_pct"] * mult
        out = _rule_outcome(atr_pool, "max_adverse_pct", threshold)
        out["rule"] = f"atr_{mult:g}x"
        universe_rows.append(out)

    day_pool = pool.dropna(subset=["worst_day_against_pct"])
    for pct in worst_day_pcts:
        out = _rule_outcome(day_pool, "worst_day_against_pct", pct)
        out["rule"] = f"worst_day_{pct:g}pct"
        universe_rows.append(out)

    universe_summary = pd.DataFrame(universe_rows)[
        ["rule", "n_flips", "pct_stopped_out", "mean_pct_move", "median_pct_move",
         "win_rate", "mean_capped_loss_when_stopped", "mean_actual_pct_move_when_stopped"]
    ]
    return per_stock, universe_summary
