# src/paper_trading.py
#
# Forward-only paper-trading journal for the debit spread and option buying
# strategies (Stages 9/11) - neither has been traded with real money yet.
# Both already have a fully backtested trade lifecycle (debit_spread_trades.py /
# option_buying_trades.py), tested on real historical data since 2023. What
# hasn't been checked is whether that same signal keeps producing a similar
# outcome distribution GOING FORWARD, on trades nobody hand-picked with
# hindsight.
#
# No new entry/exit rule is added here. This only reads each shortlisted
# symbol's already-recomputed {symbol}_trades.csv - the exact file
# process_instrument_incremental() writes when notebooks 16/19 refresh - and
# keeps the trades whose entry_date falls on or after this journal's start
# date. The start date is fixed the first time it's read (saved to
# config/paper_trading_start.json) and never moves after, so "forward" keeps
# meaning the same thing across every later run.
#
# Places no orders. Purely a read + filter + persist layer on top of
# already-tested code.

import json
import os
from datetime import datetime

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START_DATE_FILE = os.path.join(PROJECT_ROOT, "config", "paper_trading_start.json")
JOURNAL_PATH = os.path.join(PROJECT_ROOT, "logs", "paper_trading_journal.csv")

STRATEGIES = {
    "debit_spread": os.path.join(PROJECT_ROOT, "exports", "debit_spread"),
    "option_buying": os.path.join(PROJECT_ROOT, "exports", "option_buying"),
}


def get_start_date(strategy):
    """
    The date paper-tracking began for `strategy` - set the first time this is
    called for it, read back unchanged on every later call. Kept in a small
    JSON state file (not derived from the journal itself) so re-running this
    notebook can never silently move the goalposts on what counts as forward.
    """
    dates = {}
    if os.path.exists(START_DATE_FILE):
        with open(START_DATE_FILE) as f:
            dates = json.load(f)

    if strategy not in dates:
        dates[strategy] = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(os.path.dirname(START_DATE_FILE), exist_ok=True)
        with open(START_DATE_FILE, "w") as f:
            json.dump(dates, f, indent=2)

    return pd.Timestamp(dates[strategy])


def _naive(series):
    series = pd.to_datetime(series)
    return series.dt.tz_localize(None) if series.dt.tz is not None else series


def build_journal(symbols, strategy):
    """
    One row per trade opened on or after `strategy`'s paper-trading start
    date, across `symbols` - an already-refreshed shortlist, same discipline
    as the live screeners (never point this at the full universe). Includes
    both OPEN trades (still running - r_achieved is the CURRENT unrealized R
    as of the last refresh) and CLOSED trades (resolved) - `status` tells
    them apart.
    """
    exports_dir = STRATEGIES[strategy]
    start = get_start_date(strategy)

    rows = []
    for symbol in symbols:
        path = os.path.join(exports_dir, f"{symbol}_trades.csv")
        if not os.path.exists(path):
            continue
        trades = pd.read_csv(path)
        trades["entry_date"] = _naive(trades["entry_date"])
        forward = trades[trades["entry_date"] >= start].copy()
        if forward.empty:
            continue
        forward.insert(0, "strategy", strategy)
        forward.insert(1, "symbol", symbol)
        rows.append(forward)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values("entry_date").reset_index(drop=True)


def summarize(journal):
    """
    Per-strategy, per-status counts and R stats. CLOSED trades' r_achieved is
    a resolved outcome; OPEN trades' r_achieved is a live unrealized snapshot
    as of the last refresh - kept in separate rows so one never contaminates
    the other's average.
    """
    if journal.empty:
        return pd.DataFrame()

    return journal.groupby(["strategy", "status"]).agg(
        n=("symbol", "count"),
        win_rate_pct=("r_achieved", lambda r: round((r > 0).mean() * 100, 1)),
        avg_r=("r_achieved", lambda r: round(r.mean(), 3)),
        median_r=("r_achieved", lambda r: round(r.median(), 3)),
        total_r=("r_achieved", lambda r: round(r.sum(), 3)),
    ).reset_index()


def save_journal(journal):
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    journal.to_csv(JOURNAL_PATH, index=False)
    return JOURNAL_PATH
