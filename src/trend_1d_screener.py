# src/trend_1d_screener.py
#
# RENAMED from pledged_1d_screener.py (see trend_universe.py and README
# Stage 10) — live screener for the general F&O stock+index 1D
# trend-following universe, parallel to daily_screener.py, reading
# exports/trend_1d/ instead of the top-level exports/ folder. Used to also
# report ETF category / pledgeability metadata specific to the old
# pledged-securities universe; that's gone now that the
# universe IS the F&O universe (every row is directly tradable by
# construction, so a "directly_fno_tradable" column would never vary). Still
# carries security_type ("Stock"/"Index") purely for display grouping — an
# index isn't scored any differently, it just reads more naturally split out
# in a live table. This screener only reports trend state - it does not
# decide or recommend a trade.
#
# No stop-loss column here: src/stop_loss_test.py backtested fixed-%,
# ATR-multiple, and worst-day-based candidate stop rules against the real
# 1D flip history and found NONE beat holding to the natural DOWN-flip exit
# - every rule's stopped-out flips averaged a POSITIVE actual outcome had
# they been held, meaning a stop consistently cut short recoveries rather
# than preventing bigger losses (consistent with reversion_test.py's
# momentum/continuation finding). Exit is Supertrend DOWN-flip only, by
# design, not by omission. buffer_to_flip_pct/moved_since_entry_pct below
# remain the informational "how close/how underwater" numbers.

import os
import pandas as pd
from datetime import datetime

from src.trend_universe import load_trend_universe

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "trend_1d")
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
INTERVAL = "day"

MIN_DIRECTIONAL_FLIPS = 10   # lower than the 4H screener's 12 — 1D flips are rarer
OUTLIER_DAY_THRESHOLD = 4.0


def _directional_edge(flips, direction):
    """
    Did the Supertrend signal actually WORK on this instrument, in the
    direction that is open right now?

    Added because this universe turns out to be badly asymmetric (measured on
    the original 154-symbol pledged-securities universe, before the Stage 10
    repurposing to the full F&O universe — worth re-checking on the larger
    universe once enough calendar time has passed). Measured across 100
    instruments with enough history: UP flips win 54.1% with a +0.9% mean
    median move and 68% of instruments show an edge, while DOWN flips win
    42.4% with a MINUS 1.3% mean median move and only 14% show an edge. The
    median DOWN flip ends with price HIGHER than where it flipped. 27 of the
    100 have no edge in either direction.

    That matters because this strategy only ever ENTERS on a UP flip — a
    DOWN flip is purely an exit signal. On this universe that signal has
    historically worked on about one instrument in seven, so a DOWN flip on
    the other six is mostly noise, not a confirmed reversal. Without these
    columns the screener reports every flip with equal authority.

    Descriptive and in-sample, same standing as past_median below: what the
    signal HAS done on this instrument, not what it will do.
    """
    same = flips[(flips["direction"] == direction) & (flips["status"] == "CLOSED")]
    if len(same) < MIN_DIRECTIONAL_FLIPS:
        return {"dir_flips": len(same)}

    # pct_move is sign-normalised in flip_analysis.py, so positive always means
    # "went the way the signal called it" for both UP and DOWN.
    move = same["pct_move"].dropna()
    out = {
        "dir_flips": len(same),
        "dir_win_rate": round((move > 0).mean() * 100, 1),
        "dir_median_move": round(move.median(), 2),
    }
    if "worst_day_against_pct" in same.columns:
        day = same["worst_day_against_pct"].dropna()
        if len(day):
            out["worst_day"] = round(day.max(), 2)
    return out


def _has_edge(edge):
    """
    bool() cast is load-bearing: these come out of pandas as numpy scalars and
    `numpy.bool_(False) is False` is False, so identity checks downstream would
    silently never fire. Same bug bit the 4H screener twice.
    """
    if edge.get("dir_win_rate") is None:
        return None
    return bool(edge["dir_win_rate"] >= 50 and edge["dir_median_move"] > 0)


def _current_vs_flip(symbol, open_trade):
    """
    Where price sits relative to the level that would reverse the open trend.

    The single most actionable number here given there's no stop-loss —
    "0.3% from flipping" and "8% away" call for different attention, and
    neither was visible before. Reads the saved 1D candles directly, which
    is why this module touches data/raw/ as well as exports/.
    """
    path = os.path.join(RAW_DIR, f"{symbol}_{INTERVAL}.csv")
    if not os.path.exists(path):
        return {}
    try:
        raw = pd.read_csv(path, parse_dates=["date"])
    except Exception:
        return {}
    if raw.empty:
        return {}

    spot = float(raw["close"].iloc[-1])
    flip_level = float(open_trade["final_sl_at_breach"])
    entry = float(open_trade["entry_price"])
    sign = 1 if open_trade["direction"] == "UP" else -1
    return {
        "spot": round(spot, 2),
        "flip_level": round(flip_level, 2),
        "buffer_to_flip_pct": round(abs(spot - flip_level) / spot * 100, 2),
        "moved_since_entry_pct": round((spot - entry) / entry * 100 * sign, 2),
    }


def check_trend_status(symbol, universe_df=None):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        print(f"No report found for {symbol} - refresh it first")
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

    def runway(checkpoint):
        # Same signed-days form as daily_screener — easier to read at a glance
        # than three separate booleans. Descriptive only: reversion_test.py and
        # exhaustion_test.py both found that crossing a duration checkpoint
        # does NOT predict a reversal, so a negative runway is not a warning.
        return round(checkpoint - age_days, 1) if checkpoint is not None else None

    direction = open_trade["direction"]
    opposite = "DOWN" if direction == "UP" else "UP"
    edge = _directional_edge(trades, direction)
    opp_edge = _directional_edge(trades, opposite)

    result = {
        "symbol": symbol,
        "direction": direction,
        "trend_age_days": age_days,
        "median_duration": median_dur,
        "past_median": age_days > median_dur if median_dur else None,
        "past_75th_pct": age_days > p75_dur if p75_dur else None,
        "past_90th_pct": age_days > p90_dur if p90_dur else None,
        "runway_left_vs_median": runway(median_dur),
        "runway_left_vs_p75": runway(p75_dur),
        "runway_left_vs_p90": runway(p90_dur),
        # --- does the signal work on this instrument, this side? ---
        "dir_flips": edge.get("dir_flips"),
        "dir_win_rate": edge.get("dir_win_rate"),
        "dir_median_move": edge.get("dir_median_move"),
        "worst_day": edge.get("worst_day"),
        "opp_win_rate": opp_edge.get("dir_win_rate"),
        "opp_median_move": opp_edge.get("dir_median_move"),
        "signal_works_here": _has_edge(edge),
    }
    result.update(_current_vs_flip(symbol, open_trade))

    # Was this flip born on an outlier day? A trend created by a one-day
    # collapse is a different event from an orderly flip, and the duration
    # statistics above are drawn from ordinary flips.
    born = open_trade.get("born_on_outlier_day")
    move = open_trade.get("entry_day_move_pct")
    result["entry_day_move"] = round(move, 2) if pd.notna(move) else None
    result["born_on_outlier_day"] = (
        bool(born) if pd.notna(born) else None
    )

    if universe_df is not None:
        match = universe_df[universe_df["symbol"] == symbol]
        if not match.empty:
            result["security_type"] = match["security_type"].values[0]

    return result


def screen_list(symbol_list):
    """
    Same shape as daily_screener.screen_list - loads the universe once (not
    per-symbol) purely for the security_type ("Stock"/"Index") display column.
    """
    universe_df = load_trend_universe()
    results = [check_trend_status(s, universe_df=universe_df) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])
