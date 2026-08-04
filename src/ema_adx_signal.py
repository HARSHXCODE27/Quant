# src/ema_adx_signal.py
#
# NEW signal-generation module for the debit spread strategy (Stage 9).
# Parallel to flip_analysis.py, NOT a modification of it: Supertrend flips
# define a continuous regime (hold until the opposite flip), which is fine
# for premium-selling (lag is a feature there). Debit spreads pay time decay,
# so lag directly costs money -> this uses a faster, discrete trigger instead:
# EMA(9/21) crossover confirmed by a rising ADX, meant to feed a separate
# target/stop trade-lifecycle definition (NOT built yet - this module is
# signal generation only, validated on one stock before anything else).
#
# Timeframe-agnostic like the rest of src/, but intended for 1H (Kite
# interval "60minute") per the README's Stage 9 note that 4H is too laggy
# for this strategy.

import pandas as pd
import pandas_ta as ta

def apply_ema_adx(df, fast=9, slow=21, adx_period=14):
    """
    Adds EMA_{fast}, EMA_{slow}, and ADX_{adx_period} (+ DMP/DMN) columns to df.
    Uses pandas_ta, same library as supertrend.py, for consistency.
    """
    df = df.copy()
    df[f"EMA_{fast}"] = ta.ema(df["close"], length=fast)
    df[f"EMA_{slow}"] = ta.ema(df["close"], length=slow)

    adx_df = ta.adx(high=df["high"], low=df["low"], close=df["close"], length=adx_period)
    df = df.join(adx_df)
    return df

def detect_signals(df, fast=9, slow=21, adx_period=14, adx_rising_lookback=3,
                    adx_min=20, confirm_window=2):
    """
    Discrete entry signals - NOT a continuous regime like Supertrend flips.
    Every crossover is flagged whether or not confirmed, so validation can
    inspect how much the ADX filter actually removes.

    LONG:  EMA_fast crosses above EMA_slow, THEN within `confirm_window`
           candles (inclusive of the cross candle itself) ADX first becomes
           >= adx_min AND higher than `adx_rising_lookback` candles ago.
    SHORT: mirror image (EMA_fast crosses below EMA_slow).

    Why a window and not "confirmed on the exact cross candle" (the first
    version of this function): validated on BHARTIARTL 1H (Jan 2025-Jul
    2026) that the exact-candle requirement produced a 6-month dead zone
    (Feb-Jul 2026) with zero confirmed signals despite 43 crossovers and
    ADX regularly running 20-45 in that window - ADX often peaks just
    before/after the EMA cross, not exactly on it. Confirm-within-window
    kept 31/122 raw crossovers (25.4%) vs 14/122 (11.5%) for exact-candle
    and 76/122 (62%, too loose) for dropping the rising check entirely.
    (9 of the 31 fall inside the previously-dead Feb-Jul 2026 stretch.)

    The signal fires on the FIRST candle within the window where ADX
    becomes confirmed (not backdated to the cross candle) - real-time
    safe, no lookahead: at any candle t, only EMA/ADX values at or before
    t are used.

    Returns df with intermediate columns (for manual inspection during
    validation) plus a final `signal` column: 1 (long), -1 (short), 0 (none).
    """
    df = apply_ema_adx(df, fast=fast, slow=slow, adx_period=adx_period)

    ema_fast_col = f"EMA_{fast}"
    ema_slow_col = f"EMA_{slow}"
    adx_col = f"ADX_{adx_period}"

    df["ema_diff"] = df[ema_fast_col] - df[ema_slow_col]
    df["ema_cross_up"] = (df["ema_diff"] > 0) & (df["ema_diff"].shift(1) <= 0)
    df["ema_cross_down"] = (df["ema_diff"] < 0) & (df["ema_diff"].shift(1) >= 0)

    df["adx_rising"] = df[adx_col] > df[adx_col].shift(adx_rising_lookback)
    df["adx_confirmed"] = (df[adx_col] >= adx_min) & df["adx_rising"]

    cross_any = df["ema_cross_up"] | df["ema_cross_down"]

    # Direction of the most recent crossover, carried forward until superseded
    # by the next one (0 before the first crossover in the series).
    cross_dir = pd.Series(0, index=df.index)
    cross_dir[df["ema_cross_up"]] = 1
    cross_dir[df["ema_cross_down"]] = -1
    last_cross_dir = cross_dir.where(cross_dir != 0).ffill().fillna(0).astype(int)

    # Candles elapsed since the most recent crossover (0 on the cross candle
    # itself). Grouping by the cumulative crossover count naturally resets
    # this counter at every new crossover.
    group_id = cross_any.cumsum()
    since_cross = df.groupby(group_id).cumcount()

    eligible = (since_cross <= confirm_window) & df["adx_confirmed"]
    # Only the first eligible candle per crossover "regime" fires - otherwise
    # a signal would repeat on every subsequent candle that stays confirmed.
    first_eligible = eligible & ~(eligible.groupby(group_id).shift(1, fill_value=False))

    df["signal"] = 0
    df.loc[first_eligible, "signal"] = last_cross_dir[first_eligible]

    return df

def summarize_signals(df):
    """
    Quick counts for sanity-checking before scaling - not a full report yet
    (that's what flip_analysis-style trade extraction would build on top of
    this, once a target/stop lifecycle is defined).
    """
    raw_cross_ups = int(df["ema_cross_up"].sum())
    raw_cross_downs = int(df["ema_cross_down"].sum())
    long_signals = int((df["signal"] == 1).sum())
    short_signals = int((df["signal"] == -1).sum())
    total_candles = len(df)

    return {
        "total_candles": total_candles,
        "raw_ema_cross_ups": raw_cross_ups,
        "raw_ema_cross_downs": raw_cross_downs,
        "confirmed_long_signals": long_signals,
        "confirmed_short_signals": short_signals,
        "adx_filter_kept_pct": round(
            (long_signals + short_signals) / (raw_cross_ups + raw_cross_downs) * 100, 1
        ) if (raw_cross_ups + raw_cross_downs) else 0,
    }
