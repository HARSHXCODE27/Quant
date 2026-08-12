# src/flip_analysis.py
import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

def add_gap_column(df):
    """
    Adds a gap_pct column: how far each candle's open jumped from the
    previous candle's close. Catches overnight/weekend gap risk that
    intraday high/low data alone would miss.
    """
    df = df.copy()
    prev_close = df["close"].shift(1)
    df["gap_pct"] = (df["open"] - prev_close) / prev_close * 100
    return df

def add_daily_move_column(df):
    """
    Adds a daily_move_pct column: each candle tagged with the close-to-close
    move of the CALENDAR DAY it belongs to.

    This exists because add_gap_column() above only sees overnight jumps —
    open vs previous close — and that turns out to miss the larger half of
    real single-day risk. PIIND on 2026-08-12 fell 8.97% close-to-close, but
    only 1.28% of that was the opening gap; the other 7.79% happened
    intraday. To gap_pct that day looks unremarkable (well inside PIIND's
    4.06% worst historical gap), so nothing in the scoring or screening ever
    saw a near-record one-day collapse.

    Intraday collapses matter differently from gaps: a gap is unmanageable
    (you wake up already through your strike), while a grind is at least
    theoretically manageable. But both blow past the max_adverse assumptions
    a credit spread's strike distance is chosen from, and only one of them
    was being measured.

    Works on the 4H frame by grouping candles to their calendar date and
    taking each day's last close. On a 1D frame it degenerates harmlessly to
    the plain close-to-close change.
    """
    df = df.copy()
    daily_close = df["close"].groupby(df.index.normalize()).last()
    daily_move = daily_close.pct_change() * 100
    df["daily_move_pct"] = pd.Series(df.index.normalize(), index=df.index).map(daily_move)
    return df


def detect_flips(df, direction_col="SUPERTd_10_3", supertrend_col="SUPERT_10_3",
                    outlier_day_threshold=4.0):
    """
    Breaks data into segments (one per flip) and returns entry/exit stats,
    the trailing SL journey, the worst adverse move within each segment,
    the worst single gap against the position during that segment, and the
    worst single-DAY move against it.

    outlier_day_threshold is the absolute one-day move (%) at which a flip
    is marked as having been born on an abnormal day. 4% is a deliberately
    plain round number, not a fitted one — nothing here is walk-forward
    validated, so a tuned cutoff would just be overfitting the same history.
    """
    df = add_gap_column(df)
    df = add_daily_move_column(df)
    df["flip"] = df[direction_col] != df[direction_col].shift(1)
    df["segment_id"] = df["flip"].cumsum()

    trades = []
    last_segment_id = df["segment_id"].max()

    for seg_id, segment in df.groupby("segment_id"):
        direction = segment[direction_col].iloc[0]
        if pd.isna(direction):
            continue

        entry_date = segment.index[0]
        entry_price = segment["close"].iloc[0]
        initial_sl = segment[supertrend_col].iloc[0]

        if direction == 1:
            initial_sl_pct = (entry_price - initial_sl) / entry_price * 100
        else:
            initial_sl_pct = (initial_sl - entry_price) / entry_price * 100
        initial_sl_pct = round(initial_sl_pct, 2)

        # --- Max adverse move within this segment ---
        # UP: worst case is price dipping below entry -> look at the lowest low
        # DOWN: worst case is price spiking above entry -> look at the highest high
        if direction == 1:
            worst_price = segment["low"].min()
            max_adverse_pct = (entry_price - worst_price) / entry_price * 100
        else:
            worst_price = segment["high"].max()
            max_adverse_pct = (worst_price - entry_price) / entry_price * 100
        max_adverse_pct = round(max(max_adverse_pct, 0), 2)  # never negative — 0 means price never went against you

        # --- Worst single gap against the position during this segment ---
        # UP: a negative gap (price opened lower) hurts you -> want the most negative gap_pct
        # DOWN: a positive gap (price opened higher) hurts you -> want the most positive gap_pct
        if direction == 1:
            worst_gap = segment["gap_pct"].min()
            max_gap_against_pct = round(min(worst_gap, 0) * -1, 2)  # express as a positive risk number
        else:
            worst_gap = segment["gap_pct"].max()
            max_gap_against_pct = round(max(worst_gap, 0), 2)

        # --- Worst single-DAY move against the position during this segment ---
        # Same sign logic as the gap block above, but on full close-to-close
        # days rather than just the opening jump, so an intraday collapse
        # counts too. Expressed as a positive risk number, floored at 0.
        daily = segment["daily_move_pct"].dropna()
        if daily.empty:
            worst_day_against_pct = 0.0
        elif direction == 1:
            worst_day_against_pct = round(min(daily.min(), 0) * -1, 2)
        else:
            worst_day_against_pct = round(max(daily.max(), 0), 2)

        # --- Was this flip BORN on an abnormal day? ---
        # Signed raw move on the flip's entry day (negative = price fell).
        # A Supertrend flip triggered by a one-day collapse is not the same
        # event as an ordinary flip: the historical excursion stats every
        # strike distance is chosen from are drawn from ordinary flips, and
        # they do not describe a trend that began mid-crash. Recorded per
        # flip rather than derived later so the question "do crash-born
        # flips behave differently?" stays testable against history.
        entry_day_move = segment["daily_move_pct"].iloc[0]
        entry_day_move_pct = None if pd.isna(entry_day_move) else round(entry_day_move, 2)
        born_on_outlier_day = (
            entry_day_move_pct is not None
            and abs(entry_day_move_pct) > outlier_day_threshold
        )

        is_open = (seg_id == last_segment_id)

        if is_open:
            exit_date = None
            exit_price = None
            final_sl = segment[supertrend_col].iloc[-1]
            duration = None
            pct_move = None
        else:
            exit_date = segment.index[-1]
            exit_price = segment["close"].iloc[-1]
            final_sl = segment[supertrend_col].iloc[-1]
            duration = exit_date - entry_date
            if direction == 1:
                pct_move = (exit_price - entry_price) / entry_price * 100
            else:
                pct_move = (entry_price - exit_price) / entry_price * 100
            pct_move = round(pct_move, 2)

        trades.append({
            "direction": "UP" if direction == 1 else "DOWN",
            "status": "OPEN" if is_open else "CLOSED",
            "entry_date": entry_date,
            "entry_price": entry_price,
            "initial_sl": initial_sl,
            "initial_sl_pct": initial_sl_pct,
            "exit_date": exit_date,
            "exit_price": exit_price,
            "final_sl_at_breach": final_sl,
            "duration": duration,
            "pct_move": pct_move,
            "max_adverse_pct": max_adverse_pct,
            "max_gap_against_pct": max_gap_against_pct,
            "worst_day_against_pct": worst_day_against_pct,
            "entry_day_move_pct": entry_day_move_pct,
            "born_on_outlier_day": born_on_outlier_day,
            "candles_held": len(segment)
        })

    return pd.DataFrame(trades)

def save_flips(trades_df, symbol):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_flips.csv")
    trades_df.to_csv(path, index=False)
    print(f"Saved {len(trades_df)} flips to {path}")
    return path