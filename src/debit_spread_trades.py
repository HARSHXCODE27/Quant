# src/debit_spread_trades.py
#
# NEW trade-lifecycle module for the debit spread strategy (Stage 9).
# Parallel to flip_analysis.py, NOT a modification of it: flip_analysis
# defines a trade as "hold until the opposite Supertrend flip" (regime-
# following - fine for premium-selling, where lag is a feature). Debit
# spreads pay theta while open, so a stagnant "hold forever" position is a
# real cost, not neutral - this module defines trades with explicit exits
# instead: an ATR-based stop, an R-multiple target off that stop, and a
# time-based exit if neither is hit (guards against holding a going-nowhere
# position while theta bleeds).
#
# Input: the output of ema_adx_signal.detect_signals() - needs a `signal`
# column (1 long / -1 short / 0 none) plus high/low/close.

import os
import pandas as pd
import pandas_ta as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "debit_spread")

def apply_atr(df, atr_period=14):
    """
    Adds ATR_{atr_period}, used for stop-distance sizing. Not part of signal
    generation on purpose - that's ema_adx_signal.py's job; this module only
    decides how a triggered signal turns into a bounded trade.
    """
    df = df.copy()
    df[f"ATR_{atr_period}"] = ta.atr(high=df["high"], low=df["low"], close=df["close"], length=atr_period)
    return df

def simulate_trades(df, atr_period=14, atr_stop_mult=1.5, target_r_multiple=1.5,
                     time_exit_candles=14):
    """
    Walks forward from each entry signal to its exit, one trade at a time.
    A new signal is ignored while an earlier trade is still open - no
    overlapping positions; managing concurrent debit spreads on the same
    stock is a portfolio-level decision, out of scope here.

    Stop   = entry +/- atr_stop_mult * ATR_{atr_period} at the entry candle.
    Target = entry +/- target_r_multiple * (stop distance) - an R-multiple
             of risk, which is exactly what a debit spread's strike width
             would be sized around.
    Time exit = close price time_exit_candles after entry, if neither stop
                nor target was touched first (theta-decay guard - the whole
                reason this strategy needs its own lifecycle instead of
                reusing flip_analysis's "hold until reversal").

    Tie-break: if one candle's range touches BOTH stop and target (only
    possible on a wide/gappy candle), STOP wins - conservative, consistent
    with this project's worst-case framing elsewhere (max_adverse_pct,
    max_gap_against_pct in flip_analysis.py).

    Returns one row per trade: direction, entry/exit date & price, stop,
    target, exit_reason (STOP/TARGET/TIME/OPEN), candles_held, pct_move,
    r_achieved, max_adverse_pct (worst excursion against the position
    before exit - same definition as flip_analysis.py's).
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
            # Not enough data yet for a real ATR - can't size a stop, skip.
            i += 1
            continue

        stop_distance = atr_stop_mult * atr_at_entry
        target_distance = target_r_multiple * stop_distance

        if direction == "UP":
            stop_price = entry_price - stop_distance
            target_price = entry_price + target_distance
        else:
            stop_price = entry_price + stop_distance
            target_price = entry_price - target_distance

        exit_idx = None
        exit_price = None
        exit_reason = None
        worst_price = entry_price  # tracks max adverse excursion mid-trade

        max_j = min(entry_idx + time_exit_candles, n - 1)

        for j in range(entry_idx + 1, max_j + 1):
            high = df["high"].iloc[j]
            low = df["low"].iloc[j]

            if direction == "UP":
                worst_price = min(worst_price, low)
                stop_hit = low <= stop_price
                target_hit = high >= target_price
            else:
                worst_price = max(worst_price, high)
                stop_hit = high >= stop_price
                target_hit = low <= target_price

            if stop_hit:  # tie-break: stop wins if both touched same candle
                exit_idx, exit_price, exit_reason = j, stop_price, "STOP"
                break
            if target_hit:
                exit_idx, exit_price, exit_reason = j, target_price, "TARGET"
                break

        if exit_idx is None:
            if max_j == n - 1 and (entry_idx + time_exit_candles) > (n - 1):
                # Ran out of data before the time-exit horizon - still open.
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

        trades.append({
            "direction": direction,
            "status": "OPEN" if exit_reason == "OPEN" else "CLOSED",
            "entry_date": entry_date,
            "entry_price": round(entry_price, 2),
            "stop_price": round(stop_price, 2),
            "target_price": round(target_price, 2),
            "exit_date": exit_date,
            "exit_price": round(exit_price, 2),
            "exit_reason": exit_reason,
            "candles_held": exit_idx - entry_idx,
            "pct_move": round(pct_move, 2),
            "r_achieved": r_achieved,
            "max_adverse_pct": round(max_adverse_pct, 2),
        })

        i = exit_idx + 1  # resume scanning for the next signal after this trade closes

    return pd.DataFrame(trades)

def summarize_trades(trades_df):
    """
    Quick win-rate / R-distribution summary for validation - not the full
    export_report-style workbook (that comes later, once this is scaled).
    """
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
    }

def save_trades(trades_df, symbol):
    """
    Saves to exports/debit_spread/{symbol}_trades.csv - a separate
    subfolder from the existing exports/{symbol}_flips.csv and
    {symbol}_full_report.xlsx, so this strategy's outputs don't get mixed
    up with the Supertrend-based ones.
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_trades.csv")
    trades_df.to_csv(path, index=False)
    print(f"Saved {len(trades_df)} trades to {path}")
    return path
