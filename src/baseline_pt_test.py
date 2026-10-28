# src/baseline_pt_test.py
#
# Two questions about the NIFTY credit spread (README Stage 8q):
#   1. Does the 4H Supertrend timing beat the plain baseline - sell a 3% OTM
#      put spread at the start of EVERY monthly cycle, no signal, hold to expiry?
#   2. Does taking profit early (spread value down to 50% of the credit, i.e.
#      half the credit captured) beat holding to expiry / the stop?
#
# Fixed before running: 3% short strike (Stage 8l), 200-pt hedge (user's
# skip-one-strike rule), 1 lot of 65, profit-take level 50% as the primary
# (25% / 75% only as a sensitivity check). After a profit-take the trade stays flat
# until the next cycle (B) or the next flip / cycle start (A); re-selling
# straight away would just open a new trade at a new strike.
#
#   A  Supertrend  - enter on a 4H flip (bull put on UP, bear call on DOWN) or at
#                    a cycle start if the trend still points the same way; exit on
#                    the flip (stop), at expiry, or at the profit-take.
#   B  Plain puts  - at the first 4H close of each cycle sell the 3% put spread;
#                    exit at expiry or at the profit-take. No stop.
#
# Pricing: Black-Scholes, sigma = India VIX at the PREVIOUS close (no lookahead
# inside the day, no skew), intrinsic value at expiry. Costs: ₹53 to enter, ₹50
# more for an early exit (stop or profit-take); expiring trades need no exit
# order. Slippage beyond mid is NOT included. Modelled, in-sample.

import os
from datetime import datetime, time

import numpy as np
import pandas as pd

from src.black_scholes import bs_price, RISK_FREE_RATE
from src.flip_analysis import monthly_expiries
from src.ic_vs_spread_test import load_4h
from src.timeframe_indicator_test import _st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

LOT, WIDTH, STEP, STRIKE_PCT = 65, 200, 100, 3.0
ENTRY_COST, EXIT_COST = 53, 50


def _years(ts_end, exp):
    return max((datetime.combine(exp, time(15, 30)) - ts_end.to_pydatetime()).total_seconds(), 0) / (365 * 86400)


def _value(S, k, kl, T, sg, opt):
    if T <= 0:
        f = (lambda K: max(0.0, K - S)) if opt == "PE" else (lambda K: max(0.0, S - K))
        return f(k) - f(kl)
    return bs_price(S, k, T, RISK_FREE_RATE, sg, opt) - bs_price(S, kl, T, RISK_FREE_RATE, sg, opt)


def _strikes(S, up):
    if up:
        k = np.floor(S * (1 - STRIKE_PCT / 100) / STEP) * STEP
        return k, k - WIDTH, "PE"
    k = np.ceil(S * (1 + STRIKE_PCT / 100) / STEP) * STEP
    return k, k + WIDTH, "CE"


def simulate(c, vix, strategy, take_profit=None):
    """strategy 'A' (Supertrend) or 'B' (plain monthly put spread)."""
    days = c.index.date
    exps = monthly_expiries(days)
    exp_arr = np.array(exps, dtype="datetime64[D]")
    d64 = np.array(days, dtype="datetime64[D]")
    # entries use the first expiry strictly AFTER the entry day (journal rule);
    # a new cycle starts the session after an expiry, not on expiry day itself
    cycle_exp = pd.to_datetime(exp_arr[np.searchsorted(exp_arr, d64, "right")]).date
    cycle_id = np.searchsorted(exp_arr, d64, "left")
    new_cycle = np.r_[True, cycle_id[1:] != cycle_id[:-1]]
    dirs = _st(c, 10, 3).values
    close, end = c["close"].values, c["end"]
    v = vix[~vix.index.duplicated(keep="last")].sort_index()
    sig = v.shift(1).reindex(pd.to_datetime(days), method="ffill").values / 100
    last_of_day = np.r_[days[1:] != days[:-1], True]

    trades, pos = [], None

    def open_pos(i, up):
        k, kl, opt = _strikes(close[i], up)
        exp = cycle_exp[i]
        cr = _value(close[i], k, kl, _years(end.iloc[i], exp), sig[i], opt)
        return dict(i=i, up=up, k=k, kl=kl, opt=opt, exp=exp, credit=cr)

    def close_pos(p, j, reason, val):
        cost = ENTRY_COST + (EXIT_COST if reason != "EXPIRED" else 0)
        trades.append(dict(entry=c.index[p["i"]], exit=c.index[j], up=p["up"], reason=reason,
                           credit=p["credit"] * LOT, pnl=(p["credit"] - val) * LOT - cost))

    trend_at_last_exit = None
    for i in range(1, len(c)):
        if np.isnan(dirs[i]) or np.isnan(dirs[i - 1]):
            continue
        flipped = dirs[i] != dirs[i - 1]
        if pos is not None:
            p = pos
            if days[i] == p["exp"] and last_of_day[i]:
                close_pos(p, i, "EXPIRED", _value(close[i], p["k"], p["kl"], 0, 0, p["opt"]))
                pos, trend_at_last_exit = None, dirs[i]
                continue                      # new cycle starts next session
            if days[i] > p["exp"]:            # expiry fell on a day with no candle
                close_pos(p, i - 1, "EXPIRED", _value(close[i - 1], p["k"], p["kl"], 0, 0, p["opt"]))
                pos = None
            else:
                val = _value(close[i], p["k"], p["kl"], _years(end.iloc[i], p["exp"]), sig[i], p["opt"])
                if strategy == "A" and flipped:
                    close_pos(p, i, "SL_HIT", val)
                    pos = None
                elif take_profit is not None and val <= p["credit"] * (1 - take_profit):
                    close_pos(p, i, "PROFIT", val)
                    pos, trend_at_last_exit = None, dirs[i]
                    continue
        if pos is None and end.iloc[i] < c.index[-1]:
            if strategy == "B":
                if new_cycle[i] and (not trades or trades[-1]["exit"].date() < days[i]):
                    pos = open_pos(i, True)
            else:
                if flipped or (new_cycle[i] and dirs[i] == trend_at_last_exit):
                    pos = open_pos(i, dirs[i] == 1)
                    trend_at_last_exit = None
                elif new_cycle[i] and trend_at_last_exit is None and trades:
                    pos = open_pos(i, dirs[i] == 1)
    return pd.DataFrame(trades)


def run():
    c = load_4h()
    vix = pd.read_csv(os.path.join(RAW_DIR, "INDIAVIX_day.csv"), index_col=0, parse_dates=True)["close"]
    out = {}
    for strat, name in (("A", "Supertrend"), ("B", "Plain monthly put spread")):
        for tp in (None, 0.5, 0.25, 0.75):
            label = f"{name}" + (f" + take profit {int(tp * 100)}%" if tp else " (hold)")
            out[label] = simulate(c, vix, strat, tp)
    return out


def summarize(t, start="2015-02", end=None):
    months = pd.period_range(start, end or t["exit"].max().to_period("M"), freq="M")
    m = t.groupby(t["exit"].dt.to_period("M"))["pnl"].sum().reindex(months, fill_value=0.0)
    eq = m.cumsum()
    win, loss = t["pnl"][t["pnl"] > 0], t["pnl"][t["pnl"] <= 0]
    return dict(trades=len(t), win_rate=(t["pnl"] > 0).mean() * 100, avg_win=win.mean(), avg_loss=loss.mean(),
                worst_trade=t["pnl"].min(), total=t["pnl"].sum(), per_year=t["pnl"].sum() / (len(months) / 12),
                losing_months=(m < 0).mean() * 100, worst_month=m.min(), max_drawdown=(eq - eq.cummax()).min())
