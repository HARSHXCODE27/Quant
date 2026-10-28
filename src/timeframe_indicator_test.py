# src/timeframe_indicator_test.py
#
# Does a faster timeframe (1H / 2H) or a different popular trend indicator beat
# the production credit-spread signal (4H Supertrend 10,3)?
#
# Every system is run through the SAME trade rules the credit spread paper
# journal uses (src/credit_spread_journal.py), so only the signal differs:
#   - enter at the close of the candle where the signal changes direction
#     (UP -> bull put, DOWN -> bear call), short strike STRIKE_PCT OTM
#   - exit at the close of the first candle where the signal reverses (SL_HIT)
#     or at the current month's monthly expiry (EXPIRED), whichever is first
#   - after an expiry, re-enter on the next session's first candle if the
#     signal still points the same way (a fresh month, a fresh trade)
#
# Win/loss is the user's rule: SL_HIT wins only if price exited beyond entry
# in the trade's favour; EXPIRED wins unless expiry closed beyond the strike.
#
# Win rate alone cannot compare timeframes: a 1H system exits within hours and
# collects almost no time decay, a 4H one holds for weeks. So a SECOND,
# clearly-modelled measure prices the spread with Black-Scholes at entry and
# exit (src/black_scholes.py), sigma = trailing 20-day realized vol held
# constant. That is an ASSUMPTION - no IV history exists (Stage 8f), no vol
# expansion on selloffs, no skew - so the modelled P&L ranks systems against
# each other under identical assumptions; it is not an estimate of real money.
#
# All candles are built from the same 1H source (2023-01 onward) so every
# timeframe covers the identical period. In-sample, descriptive, no
# walk-forward - same standard as everything else in this project.

import os
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.black_scholes import bs_price, RISK_FREE_RATE
from src.flip_analysis import monthly_expiries   # shared NSE expiry calendar

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

STRIKE_PCT = 6.0         # short strike distance, the production default
WING_PCT = 2.0           # long strike a further 2% out -> spread width = 2% of spot
COST_PCT_OF_WIDTH = 2.0  # round-trip cost for 4 fills, as % of width (net columns only)
SESSION_HOURS = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]
BUCKETS = {
    "1H": {h: h for h in SESSION_HOURS},
    "2H": {"09:15": "09:15", "10:15": "09:15", "11:15": "11:15", "12:15": "11:15",
           "13:15": "13:15", "14:15": "13:15", "15:15": "13:15"},
    "4H": {"09:15": "09:15", "10:15": "09:15", "11:15": "09:15", "12:15": "09:15",
           "13:15": "13:15", "14:15": "13:15", "15:15": "13:15"},
}


# ---------------------------------------------------------------- candles
def load_candles(symbol, timeframe):
    """1H/2H/4H built from the saved 1H file; 1D from the saved day file."""
    if timeframe == "1D":
        df = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_day.csv"), parse_dates=["date"])
        df["date"] = pd.to_datetime(df["date"].astype(str).str[:10])
        df = df.set_index("date")
        df = df[df.index >= "2023-01-01"]
        df["end"] = df.index + pd.Timedelta(hours=15, minutes=30)
        return df[["open", "high", "low", "close", "end"]]

    df = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_60minute.csv"))
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:19])
    hhmm = df["date"].dt.strftime("%H:%M")
    df = df[hhmm.isin(SESSION_HOURS)].copy()        # drops stray 13:45/18:00 rows
    df["bucket"] = (df["date"].dt.normalize()
                    + pd.to_timedelta(df["date"].dt.strftime("%H:%M")
                                      .map(BUCKETS[timeframe]) + ":00"))
    out = df.groupby("bucket").agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   last_start=("date", "max"))
    close_of_day = out.index.normalize() + pd.Timedelta(hours=15, minutes=30)
    out["end"] = np.minimum(out["last_start"] + pd.Timedelta(hours=1), close_of_day)
    return out.drop(columns="last_start")


# ---------------------------------------------------------------- signals
def _st(df, length, mult):
    return ta.supertrend(df["high"], df["low"], df["close"], length=length,
                         multiplier=mult).iloc[:, 1]


def _cross(fast, slow):
    return np.sign(fast - slow).replace(0, np.nan).ffill()


def _psar(df):
    p = ta.psar(df["high"], df["low"], df["close"])
    return pd.Series(np.where(p.iloc[:, 0].notna(), 1, np.where(p.iloc[:, 1].notna(), -1, np.nan)),
                     index=df.index).ffill()


def _dmi(df):
    a = ta.adx(df["high"], df["low"], df["close"], length=14)
    return _cross(a["DMP_14"], a["DMN_14"])


def _donchian(df, n=20):
    hi = df["high"].rolling(n).max().shift(1)
    lo = df["low"].rolling(n).min().shift(1)
    sig = pd.Series(np.where(df["close"] > hi, 1, np.where(df["close"] < lo, -1, np.nan)),
                    index=df.index)
    return sig.ffill()


def _macd(df):
    m = ta.macd(df["close"])
    return _cross(m.iloc[:, 0], m.iloc[:, 2])


# name -> (direction series fn, entry filter fn or None). A filter only gates
# ENTRIES (sit the flip out if it disagrees); the exit is always the signal.
SYSTEMS = {
    "Supertrend 10,3":   (lambda d: _st(d, 10, 3), None),
    "Supertrend 10,2":   (lambda d: _st(d, 10, 2), None),
    "Supertrend 10,4":   (lambda d: _st(d, 10, 4), None),
    "Supertrend 7,3":    (lambda d: _st(d, 7, 3), None),
    "Supertrend 14,3":   (lambda d: _st(d, 14, 3), None),
    "EMA 9/21 cross":    (lambda d: _cross(ta.ema(d["close"], 9), ta.ema(d["close"], 21)), None),
    "EMA 20/50 cross":   (lambda d: _cross(ta.ema(d["close"], 20), ta.ema(d["close"], 50)), None),
    "MACD 12,26,9":      (_macd, None),
    "Parabolic SAR":     (_psar, None),
    "DMI +DI/-DI 14":    (_dmi, None),
    "Donchian 20":       (_donchian, None),
    "ST 10,3 + EMA200":  (lambda d: _st(d, 10, 3),
                          lambda d, s: np.sign(d["close"] - ta.ema(d["close"], 200)) == s),
    "ST 10,3 + ADX>20":  (lambda d: _st(d, 10, 3),
                          lambda d, s: ta.adx(d["high"], d["low"], d["close"])["ADX_14"] > 20),
}


# ---------------------------------------------------------------- expiries
def _realized_vol(symbol):
    d = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_day.csv"))
    d.index = pd.to_datetime(d["date"].astype(str).str[:10])
    vol = np.log(d["close"]).diff().rolling(20).std() * np.sqrt(252)
    return vol.shift(1).clip(lower=0.10)   # as known before the session; 10% floor


# ---------------------------------------------------------------- simulation
def _spread_value(S, K_short, K_long, T, sigma, up):
    opt = "PE" if up else "CE"
    return (bs_price(S, K_short, T, RISK_FREE_RATE, sigma, opt)
            - bs_price(S, K_long, T, RISK_FREE_RATE, sigma, opt))


def simulate(df, direction, entry_ok, expiries, vol):
    """Walks candles once; returns one dict per trade."""
    trades = []
    exp_dates = np.array(expiries, dtype="datetime64[D]")
    closes, ends, dirs = df["close"].values, df["end"], direction.values
    days = df.index.date
    ok = entry_ok.values if entry_ok is not None else np.ones(len(df), bool)
    pos = None

    def years_left(ts, exp):
        expiry_close = datetime.combine(exp, time(15, 30))
        return max((expiry_close - ts.to_pydatetime()).total_seconds(), 0) / (365 * 86400)

    def open_trade(i):
        exp = pd.Timestamp(exp_dates[np.searchsorted(exp_dates, np.datetime64(days[i]), "right")]).date()
        S, up = closes[i], dirs[i] == 1
        k_short = S * (1 - STRIKE_PCT / 100) if up else S * (1 + STRIKE_PCT / 100)
        k_long = S * (1 - (STRIKE_PCT + WING_PCT) / 100) if up else S * (1 + (STRIKE_PCT + WING_PCT) / 100)
        sigma = vol.asof(pd.Timestamp(days[i]))
        sigma = 0.25 if pd.isna(sigma) else sigma
        credit = _spread_value(S, k_short, k_long, years_left(ends.iloc[i], exp), sigma, up)
        return dict(i=i, up=up, entry=S, k_short=k_short, k_long=k_long, exp=exp,
                    sigma=sigma, credit=credit, width=abs(k_short - k_long), worst=S)

    def close_trade(p, j, reason):
        S, up = closes[j], p["up"]
        move = (S - p["entry"]) / p["entry"] * 100 * (1 if up else -1)
        if reason == "SL_HIT":
            win = move > 0
        else:
            win = not (S <= p["k_short"] if up else S >= p["k_short"])
        debit = _spread_value(S, p["k_short"], p["k_long"],
                              years_left(ends.iloc[j], p["exp"]), p["sigma"], up)
        adverse = (p["entry"] - p["worst"]) / p["entry"] * 100 * (1 if up else -1)
        trades.append(dict(entry_time=df.index[p["i"]], exit_time=df.index[j], up=up,
                           reason=reason, win=win, pct_move=move,
                           max_adverse=max(adverse, 0),
                           hold_days=(ends.iloc[j] - ends.iloc[p["i"]]).total_seconds() / 86400,
                           pnl_pct_width=(p["credit"] - debit) / p["width"] * 100,
                           credit_pct_width=p["credit"] / p["width"] * 100))

    for i in range(1, len(df)):
        if np.isnan(dirs[i]) or np.isnan(dirs[i - 1]):
            continue
        if pos is not None:
            pos["worst"] = (min(pos["worst"], df["low"].iat[i]) if pos["up"]
                            else max(pos["worst"], df["high"].iat[i]))
            if dirs[i] != dirs[i - 1]:
                close_trade(pos, i, "SL_HIT")
                pos = None
            elif days[i] == pos["exp"] and (i + 1 == len(df) or days[i + 1] != days[i]):
                close_trade(pos, i, "EXPIRED")
                pos = None
                continue                       # re-entry is next session's first candle
            elif days[i] > pos["exp"]:         # expiry fell where there's no candle
                close_trade(pos, i - 1, "EXPIRED")
                pos = None
        if pos is None:
            flipped = dirs[i] != dirs[i - 1]
            rolled = i > 0 and days[i] != days[i - 1] and trades and \
                trades[-1]["reason"] == "EXPIRED" and trades[-1]["exit_time"] == df.index[i - 1] \
                and trades[-1]["up"] == (dirs[i] == 1)
            if (flipped or rolled) and ok[i] and ends.iloc[i] < pd.Timestamp(df.index[-1]):
                pos = open_trade(i)
    return trades


def run_symbol(symbol, timeframes=("1H", "2H", "4H", "1D"), systems=SYSTEMS):
    vol = _realized_vol(symbol)
    rows = []
    for tf in timeframes:
        df = load_candles(symbol, tf)
        if len(df) < 300:
            continue
        expiries = monthly_expiries(df.index.date)
        for name, (sig_fn, filt_fn) in systems.items():
            direction = sig_fn(df)
            entry_ok = None
            if filt_fn is not None:
                entry_ok = filt_fn(df, direction).fillna(False)
            for t in simulate(df, direction, entry_ok, expiries, vol):
                rows.append(dict(symbol=symbol, timeframe=tf, system=name, **t))
    return rows


def data_months(symbol):
    d = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_60minute.csv"), usecols=["date"])
    span = pd.to_datetime(d["date"].iloc[-1][:10]) - pd.to_datetime(d["date"].iloc[0][:10])
    return span.days / 30.44


def summarize(trades, months):
    """
    Per (timeframe, system) - per-instrument medians so big symbols don't
    dominate. months: {symbol: months of data}, from data_months().
    """
    t = trades.copy()
    t["net_pnl"] = t["pnl_pct_width"] - COST_PCT_OF_WIDTH
    per = t.groupby(["timeframe", "system", "symbol"]).agg(
        trades=("win", "size"), win_rate=("win", "mean"),
        loss_move=("pct_move", lambda s: s[s <= 0].mean()),
        hold=("hold_days", "median"), sl_share=("reason", lambda s: (s == "SL_HIT").mean()),
        pnl_trade=("pnl_pct_width", "mean"),
        pnl_year=("net_pnl", "sum"),
    ).reset_index()
    m = per["symbol"].map(months)
    per["trades_per_month"] = per["trades"] / m
    per["pnl_year"] = per["pnl_year"] / (m / 12)
    base = per[(per.timeframe == "4H") & (per.system == "Supertrend 10,3")].set_index("symbol")["pnl_year"]
    per["beats_base"] = per.apply(lambda r: r["pnl_year"] > base.get(r["symbol"], np.inf), axis=1)
    out = per.groupby(["timeframe", "system"]).agg(
        instruments=("symbol", "nunique"),
        trades_per_month=("trades_per_month", "median"),
        win_rate=("win_rate", "median"),
        avg_loss_move=("loss_move", "median"),
        median_hold_days=("hold", "median"),
        sl_exit_share=("sl_share", "median"),
        model_pnl_per_trade=("pnl_trade", "median"),
        model_net_pnl_per_year=("pnl_year", "median"),
        pct_instruments_beating_base=("beats_base", "mean"),
    )
    out["win_rate"] *= 100
    out["sl_exit_share"] *= 100
    out["pct_instruments_beating_base"] *= 100
    return out.round(2).sort_values("model_net_pnl_per_year", ascending=False)
