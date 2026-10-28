# src/flip_analysis.py
import os
from datetime import date, timedelta

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


def monthly_expiries(trading_days):
    """
    NSE monthly expiry: last Thursday of the month up to Aug 2025, last Tuesday
    from Sep 2025 (NSE's expiry-day change). A holiday moves it to the previous
    trading day - derived from the days that actually have candles. Approximate
    for SENSEX (BSE has its own calendar).
    """
    days = sorted(set(trading_days))
    day_set = set(days)
    out = []
    y, m = days[0].year, days[0].month
    last_y, last_m = days[-1].year, days[-1].month
    stop = (last_y + 1, 1) if last_m == 12 else (last_y, last_m + 1)   # one month past the data
    while (y, m) <= stop:
        last = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1))
        weekday = 1 if (y, m) >= (2025, 9) else 3
        d = last
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        while d not in day_set and d > days[0] and d <= days[-1]:
            d -= timedelta(days=1)
        out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


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

    EXIT = THE FLIP CANDLE (fixed 2026-10-29, README Stage 8o). A closed trend
    exits at the close of the candle where the opposite flip happened - the
    first moment the flip is known. Before this fix it exited one candle early
    (the segment's last candle), which left out the candle that crossed the
    stop and inflated win rates by 15-20 pts. That candle is now also inside
    max_adverse / gap / worst-day.

    rule_trades / rule_wins - the user's credit-spread outcome, counted the way
    the paper journal trades it: a trend is split into one trade per monthly
    expiry cycle (enter on the flip; at each expiry the trade ends and a new
    one starts on the next candle). A cycle that reaches expiry with no flip
    back is a WIN; the last cycle wins only if the flip-back exit is beyond
    that cycle's own entry in its favour. The strike plays no part.
    reached_expiry = the FIRST cycle reached expiry. (1D trend-following
    ignores these columns.)
    """
    df = add_gap_column(df)
    df = add_daily_move_column(df)
    df["flip"] = df[direction_col] != df[direction_col].shift(1)
    df["segment_id"] = df["flip"].cumsum()

    trades = []
    last_segment_id = df["segment_id"].max()
    expiries = monthly_expiries(df.index.date)
    first_row = df.groupby("segment_id").head(1)       # each segment's first candle
    flip_candle = {sid - 1: row for sid, row in zip(first_row["segment_id"], first_row.index)}

    for seg_id, segment in df.groupby("segment_id"):
        direction = segment[direction_col].iloc[0]
        if pd.isna(direction):
            continue

        entry_date = segment.index[0]
        entry_price = segment["close"].iloc[0]
        initial_sl = segment[supertrend_col].iloc[0]
        final_sl = segment[supertrend_col].iloc[-1]    # the level the flip candle breached
        is_open = (seg_id == last_segment_id)
        if not is_open:
            # the trend ends ON the flip candle, so it belongs to this trade
            segment = pd.concat([segment, df.loc[[flip_candle[seg_id]]]])

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

        expiry = next((e for e in expiries if e > entry_date.date()), None)
        reached_expiry = rule_trades = rule_wins = None

        if is_open:
            exit_date = None
            exit_price = None
            duration = None
            pct_move = None
            if expiry is not None and df.index[-1].date() > expiry:
                reached_expiry = True                # still running, already past expiry
        else:
            exit_date = segment.index[-1]
            exit_price = segment["close"].iloc[-1]
            duration = exit_date - entry_date
            if direction == 1:
                pct_move = (exit_price - entry_price) / entry_price * 100
            else:
                pct_move = (entry_price - exit_price) / entry_price * 100
            pct_move = round(pct_move, 2)
            reached_expiry = bool(expiry is not None and exit_date.date() > expiry)
            passed = [e for e in expiries if entry_date.date() < e < exit_date.date()]
            last_entry = entry_price
            if passed:   # re-entry: first candle after the last expiry passed
                last_entry = segment["close"][segment.index.date > passed[-1]].iloc[0]
            last_move = (exit_price - last_entry) * (1 if direction == 1 else -1)
            rule_trades = len(passed) + 1
            rule_wins = len(passed) + int(last_move > 0)

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
            "candles_held": len(segment),
            "expiry": expiry,
            "reached_expiry": reached_expiry,
            "rule_trades": rule_trades,
            "rule_wins": rule_wins,
        })

    return pd.DataFrame(trades)

def save_flips(trades_df, symbol):
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    path = os.path.join(EXPORTS_DIR, f"{symbol}_flips.csv")
    trades_df.to_csv(path, index=False)
    print(f"Saved {len(trades_df)} flips to {path}")
    return path