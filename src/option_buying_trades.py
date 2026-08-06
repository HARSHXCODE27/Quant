# src/option_buying_trades.py
#
# NEW trade-lifecycle module for NAKED option buying (calls/puts, no hedge
# leg) - parallel to debit_spread_trades.py, NOT a modification of it. Reuses
# the exact same signal source (ema_adx_signal.detect_signals(), EMA 9/21 +
# rising-ADX confirmation, 1H) unchanged - that part is instrument-agnostic,
# it only ever looked at the underlying's price, never the spread structure.
#
# What's genuinely DIFFERENT here vs debit_spread_trades.py, and why:
#
#   Debit spread's exit uses a FIXED R-multiple target (1.5x the stop
#   distance) because a spread's own short leg already caps the payoff
#   structurally - matching the exit to that cap makes sense there.
#
#   Naked buying has no structural cap, and the entire reason to skip the
#   hedge leg is to keep that uncapped upside on a real trend run (you pay
#   for it with full premium/theta exposure instead of a net debit). A fixed
#   R target would throw that away and leave a strategy that costs MORE for
#   the SAME capped return shape as the spread - strictly worse. So this
#   module trails the stop instead of using a fixed target:
#
#     1. Same ATR-based initial stop as debit_spread_trades.py (entry +/-
#        atr_stop_mult * ATR_{atr_period} at entry).
#     2. Once price has moved in favor by >= trail_activate_r * (initial stop
#        distance), the stop starts trailing the best price seen since entry,
#        offset by the SAME atr_stop_mult * entry-ATR distance (fixed at
#        entry, not recomputed candle-by-candle - keeps this a deterministic,
#        no-lookahead walk-forward, same principle as flip_analysis.py's
#        rules and ema_adx_signal.py's confirm_window fix).
#     3. Before trailing activates, the ONLY way out is the initial stop or
#        the time exit - there is no fixed target to hit.
#     4. Time exit (same 14-candle default as debit spread) is kept as a
#        safety net even with a trailing stop - theta still bleeds on a
#        naked long option the whole time it's open, so a trade that never
#        even reaches trail-activation still needs to close out on a clock,
#        not just hold hoping for a big move.
#
# CAVEAT carried over from debit_spread_trades.py, and worse here, not
# better: this still only simulates the UNDERLYING's price move as a proxy
# for the trade's real P&L. That proxy was already imperfect for a spread;
# it's weaker for naked buying, since a naked long option has full exposure
# to theta decay and IV changes with nothing offsetting it (a spread's short
# leg absorbs some of both). Treat pct_move/r_achieved here as a signal-
# quality filter, not an expected real return - state this plainly, don't
# bury it (same standard applied to the debit-spread proxy note in the
# README).

import os
import pandas as pd
import pandas_ta as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "option_buying")
FOUR_H_EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def apply_atr(df, atr_period=14):
    """Same as debit_spread_trades.py's apply_atr - stop-distance sizing only."""
    df = df.copy()
    df[f"ATR_{atr_period}"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=atr_period)
    return df

def apply_4h_trend_filter(df, symbol):
    """
    HARD FILTER - zeroes out any 1H signal that disagrees with the direction
    of the symbol's own 4H Supertrend trend at that moment (reads the SAME
    exports/{symbol}_full_report.xlsx every other strategy in this project
    already uses - not a new signal, a filter on top of the existing one).

    Tested finding (12,608 real closed 1H trades, 214 instruments, matched
    to their 4H trend state at entry): aligned entries won 53.3% vs 47.2%
    against, mean R 0.166 vs 0.024, and - the number that actually mattered -
    median R flipped from +0.08 (aligned) to -0.46 (against). The typical
    against-trend trade loses; the typical aligned trade doesn't. See README
    Stage 11 for the full writeup.

    A 1H signal candle with no matching 4H flip window (e.g. before that
    symbol's 4H history starts, or a gap between two saved flip records) is
    dropped, not defaulted to "aligned" - conservative, consistent with
    "only trade when the higher-timeframe context is actually known."

    Adds a `four_h_direction` column (the 4H direction active at each
    surviving signal candle, for audit - every signal remaining after this
    filter will show it, by construction) - simulate_trades() picks it up
    into the trade record if present.
    """
    df = df.copy()
    path = os.path.join(FOUR_H_EXPORTS_DIR, f"{symbol}_full_report.xlsx")

    if "signal" not in df.columns:
        return df

    if not os.path.exists(path):
        # No 4H data available for this symbol at all - can't confirm
        # alignment, so no signal can pass. Conservative, not optimistic.
        df["signal"] = 0
        df["four_h_direction"] = None
        return df

    flips = pd.read_excel(path, sheet_name="Flips")
    flips["entry_date"] = pd.to_datetime(flips["entry_date"])
    if flips["entry_date"].dt.tz is not None:
        flips["entry_date"] = flips["entry_date"].dt.tz_localize(None)
    flips["exit_date"] = pd.to_datetime(flips["exit_date"])
    if flips["exit_date"].dt.tz is not None:
        flips["exit_date"] = flips["exit_date"].dt.tz_localize(None)
    flips = flips.sort_values("entry_date").reset_index(drop=True)

    def direction_at(ts):
        ts = pd.Timestamp(ts)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        match = flips[(flips["entry_date"] <= ts) &
                       (flips["exit_date"].isna() | (flips["exit_date"] >= ts))]
        if match.empty:
            return None
        return match.iloc[-1]["direction"]

    four_h_dirs = []
    for ts, sig in zip(df.index, df["signal"]):
        if sig == 0:
            four_h_dirs.append(None)
            continue
        four_h_dirs.append(direction_at(ts))
    df["four_h_direction"] = four_h_dirs

    signal_dir = df["signal"].map({1: "UP", -1: "DOWN", 0: None})
    aligned = signal_dir == df["four_h_direction"]
    df.loc[~aligned, "signal"] = 0

    return df

def simulate_trades(df, atr_period=14, atr_stop_mult=1.5, trail_activate_r=1.0,
                     time_exit_candles=14):
    """
    Walks forward from each entry signal to its exit, one trade at a time -
    same no-overlap rule as debit_spread_trades.py (a new signal is ignored
    while an earlier trade is still open).

    Stop starts at entry -/+ atr_stop_mult * ATR_{atr_period} (fixed at
    entry). Once the trade's open r_achieved-so-far reaches
    trail_activate_r, the stop begins trailing the best price seen since
    entry by the same atr_stop_mult * entry-ATR distance, ratcheting in the
    trade's favor only (never loosens) - same one-way-ratchet principle
    Supertrend itself uses for its bands.

    No fixed target - the trade only closes via TRAIL_STOP (stop hit after
    trailing activated), STOP (initial stop hit before trailing activated),
    or TIME (time_exit_candles reached with neither stop touched).

    Returns one row per trade: direction, entry/exit date & price, stop
    levels, exit_reason (STOP/TRAIL_STOP/TIME/OPEN), candles_held, pct_move,
    r_achieved, max_adverse_pct - same column shape as debit_spread_trades.py
    minus target_price (replaced by trail_activated/best_price_reached for
    inspection), so the two are easy to compare side by side.
    """
    df = apply_atr(df, atr_period=atr_period)
    atr_col = f"ATR_{atr_period}"

    trades = []
    i = 0
    n = len(df)

    while i < n:
        signal = df["signal"].iloc[i]
        if signal == 0:
            i += 1
            continue

        direction = "UP" if signal == 1 else "DOWN"
        entry_idx = i
        entry_date = df.index[i]
        entry_price = df["close"].iloc[i]
        atr_at_entry = df[atr_col].iloc[i]

        if pd.isna(atr_at_entry):
            i += 1
            continue

        stop_distance = atr_stop_mult * atr_at_entry
        trail_trigger_distance = trail_activate_r * stop_distance

        if direction == "UP":
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        trailing_active = False
        best_price = entry_price
        worst_price = entry_price
        exit_idx = None
        exit_price = None
        exit_reason = None

        max_j = min(entry_idx + time_exit_candles, n - 1)

        for j in range(entry_idx + 1, max_j + 1):
            high = df["high"].iloc[j]
            low = df["low"].iloc[j]

            if direction == "UP":
                worst_price = min(worst_price, low)
                best_price = max(best_price, high)

                # Stop check first (conservative tie-break, same as debit_spread_trades.py)
                if low <= stop_price:
                    exit_idx = j
                    exit_price = stop_price
                    exit_reason = "TRAIL_STOP" if trailing_active else "STOP"
                    break

                if not trailing_active and (best_price - entry_price) >= trail_trigger_distance:
                    trailing_active = True

                if trailing_active:
                    new_stop = best_price - stop_distance
                    stop_price = max(stop_price, new_stop)  # ratchet up only

            else:
                worst_price = max(worst_price, high)
                best_price = min(best_price, low)

                if high >= stop_price:
                    exit_idx = j
                    exit_price = stop_price
                    exit_reason = "TRAIL_STOP" if trailing_active else "STOP"
                    break

                if not trailing_active and (entry_price - best_price) >= trail_trigger_distance:
                    trailing_active = True

                if trailing_active:
                    new_stop = best_price + stop_distance
                    stop_price = min(stop_price, new_stop)  # ratchet down only

        if exit_idx is None:
            if max_j == n - 1 and (entry_idx + time_exit_candles) > (n - 1):
                exit_idx = n - 1
                exit_price = df["close"].iloc[-1]
                exit_reason = "OPEN"
            else:
                exit_idx = max_j
                exit_price = df["close"].iloc[max_j]
                exit_reason = "TIME"

        exit_date = df.index[exit_idx]

        if direction == "UP":
            pct_move = (exit_price - entry_price) / entry_price * 100
            max_adverse_pct = max((entry_price - worst_price) / entry_price * 100, 0)
        else:
            pct_move = (entry_price - exit_price) / entry_price * 100
            max_adverse_pct = max((worst_price - entry_price) / entry_price * 100, 0)

        risk_pct = stop_distance / entry_price * 100
        r_achieved = round(pct_move / risk_pct, 2) if risk_pct else None

        trade_row = {
            "direction": direction,
            "status": "OPEN" if exit_reason == "OPEN" else "CLOSED",
            "entry_date": entry_date,
            "entry_price": round(entry_price, 2),
            "initial_stop_price": round(entry_price - stop_distance, 2) if direction == "UP" else round(entry_price + stop_distance, 2),
            "final_stop_price": round(stop_price, 2),
            "trailing_activated": trailing_active,
            "exit_date": exit_date,
            "exit_price": round(exit_price, 2),
            "exit_reason": exit_reason,
            "candles_held": exit_idx - entry_idx,
            "pct_move": round(pct_move, 2),
            "r_achieved": r_achieved,
            "max_adverse_pct": round(max_adverse_pct, 2),
        }
        # If apply_4h_trend_filter() ran upstream, every surviving signal is
        # aligned by construction - recorded anyway as an audit trail (proves
        # the filter actually ran, and shows what backed the entry).
        if "four_h_direction" in df.columns:
            trade_row["four_h_direction"] = df["four_h_direction"].iloc[entry_idx]
        trades.append(trade_row)

        i = exit_idx + 1

    return pd.DataFrame(trades)

def summarize_trades(trades_df):
    """Same shape as debit_spread_trades.py's summarize_trades, for direct comparison."""
    if trades_df.empty:
        return {"total_trades": 0, "closed_trades": 0}

    closed = trades_df[trades_df["status"] == "CLOSED"]
    if closed.empty:
        return {"total_trades": len(trades_df), "closed_trades": 0}

    wins = closed[closed["pct_move"] > 0]

    return {
        "total_trades": len(trades_df),
        "closed_trades": len(closed),
        "open_trades": len(trades_df) - len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1),
        "avg_r_achieved": round(closed["r_achieved"].mean(), 2),
        "median_r_achieved": round(closed["r_achieved"].median(), 2),
        "exit_reason_counts": closed["exit_reason"].value_counts().to_dict(),
        "median_candles_held": round(closed["candles_held"].median(), 1),
        "pct_trades_trailing_activated": round(closed["trailing_activated"].mean() * 100, 1),
    }

def save_trades(trades_df, symbol):
    """Saves to exports/option_buying/{symbol}_trades.csv - own subfolder, no collision
    with exports/debit_spread/ or the Supertrend-based exports."""
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_trades.csv")
    trades_df.to_csv(path, index=False)
    print(f"Saved {len(trades_df)} trades to {path}")
    return path
