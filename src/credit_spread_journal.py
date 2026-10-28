# src/credit_spread_journal.py
#
# Forward-only paper-trading journal for the credit spread final list
# (notebook 06 / scripts/daily_list.py). Every symbol that appears on the
# final list is logged as a trade taken at that moment, then tracked on every
# later run until exactly one of two exits happens - whether or not the
# symbol is still on the list:
#
#   SL_HIT  - a COMPLETED 4H candle closes beyond the trailing Supertrend
#             (10,3) level, i.e. the flip. Same exit every flip statistic in
#             this project is built on. initial_sl (level when logged) and
#             sl_at_exit (level that was actually breached) are both
#             recorded, so "stopped before the stop trailed past entry" stays
#             visible.
#   EXPIRED - reached the option expiry with no SL hit. Always the CURRENT
#             month's monthly expiry, by the user's choice (on expiry day
#             itself the next month's is used - that day's contract is gone
#             within hours).
#
# Deliberately NOT exits (tested or untested elsewhere - see README):
# profit targets, DTE rules, strike-touch. Strike touch is only RECORDED
# (strike_touched, expired_beyond_strike) - that is the question the journal
# exists to answer, not a rule to trade on.
#
# Unlike src/paper_trading.py (which re-derives trades from backtest files on
# every run) this journal is APPEND-ONLY STATE: a trade exists because the
# list showed it on that day, and cannot be reconstructed later. That is why
# it lives in logs/ (tracked in git), not exports/.
#
# Places no orders. Only completed candles are evaluated - a 13:20 run sees
# the 13:15 candle partially formed, and a partial close beyond the line can
# reverse before 15:30.

import os
from datetime import datetime, timedelta

import pandas as pd

from src.supertrend import load_raw_data, apply_supertrend

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL_PATH = os.path.join(PROJECT_ROOT, "logs", "credit_spread_journal.csv")

COLUMNS = [
    "trade_id", "symbol", "structure", "direction", "sector", "setup_score",
    "logged_at", "flip_date", "entry_spot", "short_strike", "strike_buffer_pct",
    "initial_sl", "adx_at_flip", "expiry",
    # spread + sizing (src/spread_builder.py, from 2026-10-28; blank before)
    "long_strike", "option_exchange", "lots", "credit", "margin_rupees",
    "return_on_margin_pct", "max_loss_rupees",
    "status", "exit_reason", "exit_date", "exit_spot", "sl_at_exit",
    "pct_move", "max_adverse_pct", "strike_touched", "expired_beyond_strike",
    "days_held", "last_checked",
]

MARKET_CLOSE = (15, 30)
from src.instruments import INDEX_SYMBOLS   # SENSEX lives on BSE


def load_journal():
    # dtype=object: columns start empty (exit_* on a fresh trade) and get
    # strings written into them later; pandas 3 refuses that on a float column.
    if not os.path.exists(JOURNAL_PATH):
        return pd.DataFrame(columns=COLUMNS, dtype=object)
    journal = pd.read_csv(JOURNAL_PATH, dtype=object)
    # Columns added after a journal was started (adx_at_flip, 2026-10-28)
    # stay blank on the older rows rather than being back-filled.
    for col in COLUMNS:
        if col not in journal.columns:
            journal[col] = None
    return journal.astype(object)


def save_journal(journal):
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    journal[COLUMNS].to_csv(JOURNAL_PATH, index=False)


def open_symbols(journal=None):
    journal = load_journal() if journal is None else journal
    return journal[journal["status"] == "OPEN"]["symbol"].unique().tolist()


def refresh_symbols(kite, symbols, to_date=None):
    """
    Incremental 4H catch-up for symbols with an OPEN trade that today's
    shortlist did not already refresh - a trade keeps being tracked after its
    symbol drops off the list, so its candles must keep coming in. Returns a
    list of "symbol: error" strings, same convention as daily_list.refresh().
    """
    from src.instruments import build_nse_token_lookup, get_index_token
    from src.scale_pipeline import process_stock_incremental

    if not symbols:
        return []
    to_date = to_date or datetime.now()
    lookup = build_nse_token_lookup(kite)
    failed = []
    for symbol in symbols:
        try:
            if symbol in INDEX_SYMBOLS:
                ts, ex = INDEX_SYMBOLS[symbol]
                token = get_index_token(kite, ts, ex)
            else:
                token = lookup.get(symbol)
            if token is None:
                failed.append(f"{symbol}: no token")
                continue
            process_stock_incremental(symbol, token, kite, to_date=to_date)
        except Exception as e:
            failed.append(f"{symbol}: {e}")
    return failed


def monthly_expiries(kite):
    """
    symbol -> sorted list of MONTHLY option expiry dates, from Kite's NFO + BFO
    instrument dumps (real dates, holidays already applied). Monthly = the
    last listed expiry in each calendar month, which drops the weeklies.
    """
    from src.spread_builder import option_chain, monthly_expiries as _monthly
    return _monthly(option_chain(kite))


def current_month_expiry(symbol, expiries, today=None):
    """First monthly expiry strictly after today (see header for expiry day)."""
    today = today or datetime.now().date()
    for exp in expiries.get(symbol, []):
        if exp > today:
            return exp
    return None


def _supertrend_frame(symbol):
    df = apply_supertrend(load_raw_data(symbol, "4hour"))
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _last_flip_date(symbol, now):
    d = _supertrend_frame(symbol)["SUPERTd_10_3"]
    d = d[d.index <= now]
    flips = d.index[d != d.shift(1)]
    return str(flips[-1]) if len(flips) else None


def _candle_end(start):
    """4H candles start 09:15 and 13:15; the second is cut short by the close."""
    close = start.replace(hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0)
    return min(start + timedelta(hours=4), close)


def _evaluate(trade, now):
    """
    Walks the completed 4H candles since the trade was logged and returns the
    fields to update. Exit is decided on candle CLOSE against the Supertrend
    level standing BEFORE that candle (the level a stop order would sit at).
    """
    df = _supertrend_frame(trade["symbol"])

    logged_at = pd.Timestamp(trade["logged_at"])
    expiry = pd.Timestamp(trade["expiry"]).date()
    up = trade["direction"] == "UP"
    entry = float(trade["entry_spot"])
    strike = float(trade["short_strike"])

    df["prev_st"] = df["SUPERT_10_3"].shift(1)
    ends = df.index.map(_candle_end)
    done = df[(ends > logged_at) & (ends <= now) & (df.index.date <= expiry)]

    worst = entry
    touched = False
    result = {"last_checked": now.strftime("%Y-%m-%d %H:%M")}

    for ts, c in done.iterrows():
        worst = min(worst, c["low"]) if up else max(worst, c["high"])
        touched = touched or (c["low"] <= strike if up else c["high"] >= strike)
        flipped = c["SUPERTd_10_3"] == (-1 if up else 1)
        if flipped:
            result.update(status="CLOSED", exit_reason="SL_HIT", exit_date=str(ts),
                          exit_spot=c["close"], sl_at_exit=round(c["prev_st"], 2))
            break

    if "exit_reason" not in result:
        expiry_close = datetime.combine(expiry, datetime.min.time()).replace(
            hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1])
        # Saved data must reach the expiry date (or past it, if expiry fell on
        # a holiday) - otherwise the last candles before expiry may simply not
        # be fetched yet, and the trade stays OPEN until a refresh brings them.
        data_reaches_expiry = df.index.max().date() >= expiry
        if now >= expiry_close and data_reaches_expiry and not done.empty:
            last = done.iloc[-1]
            result.update(status="CLOSED", exit_reason="EXPIRED",
                          exit_date=str(done.index[-1]), exit_spot=last["close"],
                          expired_beyond_strike=bool(last["close"] <= strike if up
                                                     else last["close"] >= strike))

    adverse = (entry - worst) / entry * 100 if up else (worst - entry) / entry * 100
    result["max_adverse_pct"] = round(max(adverse, 0), 2)
    result["strike_touched"] = touched

    if "exit_spot" in result:
        exit_spot = float(result["exit_spot"])
        move = (exit_spot - entry) / entry * 100 if up else (entry - exit_spot) / entry * 100
        result["pct_move"] = round(move, 2)
        result["days_held"] = round((pd.Timestamp(result["exit_date"]) - logged_at)
                                    .total_seconds() / 86400, 1)
    return result


def update_open_trades(journal, now=None):
    now = now or datetime.now()
    for i in journal.index[journal["status"] == "OPEN"]:
        try:
            for col, val in _evaluate(journal.loc[i], now).items():
                journal.loc[i, col] = val
        except Exception as e:
            print(f"  could not evaluate {journal.loc[i, 'symbol']}: {e}")
    return journal


def record_entries(journal, final, expiries, now=None):
    """
    Logs every row of the final list as a trade, unless that symbol already
    has an OPEN trade (one position per symbol - re-appearing on the list the
    next day is the same trade, not a new one). Run update_open_trades()
    FIRST, so a symbol whose old trade just hit SL can be re-entered on its
    new flip. Returns (journal, logged, skipped).
    """
    now = now or datetime.now()
    already_open = set(open_symbols(journal))
    rows, skipped = [], []
    next_id = int(pd.to_numeric(journal["trade_id"]).max()) + 1 if not journal.empty else 1

    for _, r in final.iterrows():
        if r["symbol"] in already_open:
            continue
        # A spread that couldn't be priced, or whose single lot already
        # breaks the max-loss cap, is not a trade the user would take.
        if pd.notna(r.get("spread_problem")):
            skipped.append(f"{r['symbol']}: not logged - {r['spread_problem']}")
            continue
        if bool(r.get("lot_too_big", False)):
            skipped.append(f"{r['symbol']}: not logged - one lot's max loss "
                           f"₹{r['max_loss_per_lot']:,.0f} is over the per-trade cap")
            continue
        expiry = (pd.Timestamp(r["expiry"]).date() if pd.notna(r.get("expiry"))
                  else current_month_expiry(r["symbol"], expiries, now.date()))
        if expiry is None:
            skipped.append(f"{r['symbol']}: no monthly option expiry found")
            continue
        rows.append({
            "trade_id": next_id, "symbol": r["symbol"],
            "structure": "BULL PUT" if r["direction"] == "UP" else "BEAR CALL",
            "direction": r["direction"], "sector": r.get("sector"),
            "setup_score": r.get("setup_score"),
            "logged_at": now.strftime("%Y-%m-%d %H:%M"),
            "flip_date": _last_flip_date(r["symbol"], now),
            "entry_spot": r["spot"], "short_strike": r["short_strike"],
            "strike_buffer_pct": (r["strike_distance_pct"] if pd.notna(r.get("strike_distance_pct"))
                                  else r.get("strike_buffer_pct")),
            "initial_sl": r["flip_level"], "adx_at_flip": r.get("adx_at_flip"),
            "expiry": str(expiry),
            "long_strike": r.get("long_strike"), "option_exchange": r.get("option_exchange"),
            "lots": r.get("lots"), "credit": r.get("credit"),
            "margin_rupees": (r["margin_per_lot"] * r["lots"]
                              if pd.notna(r.get("margin_per_lot")) else None),
            "return_on_margin_pct": r.get("return_on_margin_pct"),
            "max_loss_rupees": r.get("max_loss_total"),
            "status": "OPEN", "strike_touched": False,
            "last_checked": now.strftime("%Y-%m-%d %H:%M"),
        })
        next_id += 1

    if rows:
        new = pd.DataFrame(rows, columns=COLUMNS).astype(object)
        journal = new if journal.empty else pd.concat([journal, new], ignore_index=True)
    return journal, [r["symbol"] for r in rows], skipped


def run_journal(kite, final, already_refreshed=()):
    """
    One call per screener run: refresh candles for open trades the shortlist
    didn't cover, close any that hit SL / expired, then log today's list.
    """
    journal = load_journal()
    extra = [s for s in open_symbols(journal) if s not in set(already_refreshed)]
    errors = refresh_symbols(kite, extra)

    journal = update_open_trades(journal)
    journal, logged, skipped = record_entries(journal, final, monthly_expiries(kite))
    save_journal(journal)
    return journal, logged, skipped + errors


def summarize(journal):
    """Counts and average move by exit reason. Empty frame if nothing closed."""
    closed = journal[journal["status"] == "CLOSED"]
    if closed.empty:
        return pd.DataFrame()
    closed = closed.assign(pct_move=pd.to_numeric(closed["pct_move"]))
    return closed.groupby(["structure", "exit_reason"]).agg(
        trades=("trade_id", "count"),
        avg_pct_move=("pct_move", "mean"),
        median_pct_move=("pct_move", "median"),
        strike_touched=("strike_touched", lambda s: int(s.astype(str).eq("True").sum())),
    ).round(2)
