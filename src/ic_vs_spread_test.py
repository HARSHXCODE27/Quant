# src/ic_vs_spread_test.py
#
# NIFTY: at the start of each monthly expiry cycle, does the market state say
# "short iron condor" or "directional credit spread"? (README Stage 8m)
#
# Two strategies, priced the same way (Black-Scholes, sigma = India VIX, no
# skew - the Stage 8l model), one lot (current 65), user's 200-pt hedges:
#   IC  - at the close of the cycle's first 4H candle, sell 7% OTM call + put
#         (rounded outward to 100), buy 200 pts beyond each. Exit when price
#         touches either short strike (the user's loss rule), else hold to
#         expiry. Costs: ₹110 per 4 orders.
#   CS  - the production signal: 4H Supertrend 10,3 bull put / bear call at a
#         3% OTM short strike (Stage 8l), exit at the flip or expiry; every
#         trade ENTERED in the cycle counts toward it. Costs ₹53 entry, ₹50
#         more at an SL exit.
#
# Regime signals, fixed BEFORE running (standard settings, nothing tuned):
#   VIX percentile vs the trailing 252 sessions (prior close) - Stage 8j: high
#     VIX meant moves beyond VIX's own implied range
#   daily ADX(14) on NIFTY (prior close) - < 20 range-bound, > 25 trending
# Rule under test: IC when ADX < 20 and VIX percentile <= 66, else CS.
# Built on 2015-2021, checked unchanged on 2022-2026.
#
# Data: data/raw/NIFTY_60minute_2015.csv (1H from 2015, resampled to 4H the
# same way as Stage 8g), INDIAVIX_day.csv, NIFTY_day.csv. In-sample model,
# not real option prices: real 7% puts trade ABOVE VIX (skew), which this
# understates for the IC's put side.

import os
from datetime import datetime, time

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.black_scholes import bs_price, RISK_FREE_RATE
from src.timeframe_indicator_test import (SESSION_HOURS, BUCKETS, simulate,
                                          monthly_expiries, _st)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

LOT, WIDTH, STEP = 65, 200, 100
IC_PCT, CS_PCT = 7.0, 3.0
IC_COST, CS_ENTRY_COST, CS_EXIT_COST = 110, 53, 50
ADX_RANGE, VIX_HIGH_PCTILE = 20, 66


def load_4h():
    df = pd.read_csv(os.path.join(RAW_DIR, "NIFTY_60minute_2015.csv"), parse_dates=["date"])
    hhmm = df["date"].dt.strftime("%H:%M")
    df = df[hhmm.isin(SESSION_HOURS)].copy()
    df["bucket"] = df["date"].dt.normalize() + pd.to_timedelta(
        df["date"].dt.strftime("%H:%M").map(BUCKETS["4H"]) + ":00")
    out = df.groupby("bucket").agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   last_start=("date", "max"))
    close_of_day = out.index.normalize() + pd.Timedelta(hours=15, minutes=30)
    out["end"] = np.minimum(out["last_start"] + pd.Timedelta(hours=1), close_of_day)
    return out.drop(columns="last_start")


def signals():
    """Per trading day, values known at the PREVIOUS close."""
    vix = pd.read_csv(os.path.join(RAW_DIR, "INDIAVIX_day.csv"), index_col=0, parse_dates=True)["close"]
    pct = vix.rolling(253).apply(lambda s: (s[:-1] < s[-1]).mean() * 100, raw=True)
    day = pd.read_csv(os.path.join(RAW_DIR, "NIFTY_day.csv"))
    day.index = pd.to_datetime(day["date"].astype(str).str[:10])
    adx = ta.adx(day["high"], day["low"], day["close"], length=14)["ADX_14"]
    return pd.DataFrame({"vix": vix, "vix_pct": pct}).shift(1), adx.shift(1), vix


def _years(ts, exp):
    return max((datetime.combine(exp, time(15, 30)) - ts.to_pydatetime()).total_seconds(), 0) / (365 * 86400)


def _vertical(S, k, k_long, T, sigma, opt):
    return bs_price(S, k, T, RISK_FREE_RATE, sigma, opt) - bs_price(S, k_long, T, RISK_FREE_RATE, sigma, opt)


def iron_condor(c4, start, exp, vix_close):
    """One IC for the cycle; returns dict with pnl, breached, side."""
    cyc = c4[(c4.index.date >= start) & (c4.index.date <= exp)]
    if cyc.empty:
        return None
    S0, t0 = cyc["close"].iloc[0], cyc["end"].iloc[0]
    kc = np.ceil(S0 * (1 + IC_PCT / 100) / STEP) * STEP
    kp = np.floor(S0 * (1 - IC_PCT / 100) / STEP) * STEP
    sig0 = vix_close.asof(pd.Timestamp(start) - pd.Timedelta(days=1)) / 100
    T0 = _years(t0, exp)
    value = lambda S, T, sg: (_vertical(S, kc, kc + WIDTH, T, sg, "CE")
                              + _vertical(S, kp, kp - WIDTH, T, sg, "PE"))
    credit = value(S0, T0, sig0)
    for ts, r in cyc.iloc[1:].iterrows():
        hit_c, hit_p = r["high"] >= kc, r["low"] <= kp
        if hit_c or hit_p:
            S = (max(r["open"], kc) if hit_c else min(r["open"], kp))   # stop at the strike, or the gap
            sg = vix_close.asof(ts.normalize()) / 100
            exit_val = value(S, _years(r["end"], exp), sg)
            return dict(ic_pnl=(credit - exit_val) * LOT - 2 * IC_COST, ic_breached=True,
                        ic_side="CALL" if hit_c else "PUT", ic_credit=credit * LOT)
    S = cyc["close"].iloc[-1]
    exit_val = value(S, 0, 0.01)
    return dict(ic_pnl=(credit - exit_val) * LOT - IC_COST, ic_breached=False, ic_side=None,
                ic_credit=credit * LOT)


def credit_spreads(c4, expiries, vix_close):
    """Production 4H Supertrend trades re-priced at a 3% strike; one row per trade."""
    direction = _st(c4, 10, 3)
    rv = pd.Series(0.15, index=pd.to_datetime(sorted(set(c4.index.normalize()))))
    exp_arr = np.array(expiries, dtype="datetime64[D]")
    rows = []
    for t in simulate(c4, direction, None, expiries, rv):
        S0, t0 = c4.loc[t["entry_time"], "close"], c4.loc[t["entry_time"], "end"]
        S1, t1 = c4.loc[t["exit_time"], "close"], c4.loc[t["exit_time"], "end"]
        exp = pd.Timestamp(exp_arr[np.searchsorted(exp_arr, np.datetime64(t["entry_time"].date()), "right")]).date()
        up = t["up"]
        opt = "PE" if up else "CE"
        k = (np.floor(S0 * (1 - CS_PCT / 100) / STEP) * STEP if up
             else np.ceil(S0 * (1 + CS_PCT / 100) / STEP) * STEP)
        kl = k - WIDTH if up else k + WIDTH
        sig0 = vix_close.asof(t["entry_time"].normalize() - pd.Timedelta(days=1)) / 100
        sig1 = vix_close.asof(t["exit_time"].normalize()) / 100
        T1 = _years(t1, exp)
        exit_val = (_vertical(S1, k, kl, T1, sig1, opt) if T1 > 0
                    else max(0, min(WIDTH, (k - S1) if up else (S1 - k))))
        credit = _vertical(S0, k, kl, _years(t0, exp), sig0, opt)
        cost = CS_ENTRY_COST + (CS_EXIT_COST if t["reason"] == "SL_HIT" else 0)
        rows.append(dict(entry=t["entry_time"], reason=t["reason"],
                         cs_pnl=(credit - exit_val) * LOT - cost))
    return pd.DataFrame(rows)


def run():
    c4 = load_4h()
    days = sorted(set(c4.index.date))
    expiries = monthly_expiries(days)
    sig, adx, vix_close = signals()
    cs = credit_spreads(c4, expiries, vix_close)
    rows = []
    for prev, exp in zip(expiries[:-1], expiries[1:]):
        start = next((d for d in days if d > prev), None)
        if start is None or exp > days[-1] or start > exp:
            continue
        ic = iron_condor(c4, start, exp, vix_close)
        if ic is None:
            continue
        ts = pd.Timestamp(start)
        in_cyc = cs[(cs["entry"].dt.date >= start) & (cs["entry"].dt.date <= exp)]
        rows.append(dict(cycle_start=start, expiry=exp, vix=sig["vix"].asof(ts),
                         vix_pct=sig["vix_pct"].asof(ts), adx=adx.asof(ts),
                         cs_pnl=in_cyc["cs_pnl"].sum(), cs_trades=len(in_cyc), **ic))
    m = pd.DataFrame(rows).dropna(subset=["vix_pct", "adx"])
    m["rule_ic"] = (m["adx"] < ADX_RANGE) & (m["vix_pct"] <= VIX_HIGH_PCTILE)
    m["rule_pnl"] = np.where(m["rule_ic"], m["ic_pnl"], m["cs_pnl"])
    m["period"] = np.where(pd.to_datetime(m["cycle_start"]).dt.year <= 2021, "2015-21 (built)", "2022-26 (holdout)")
    return m


def summarize(m):
    out = []
    for period, g in list(m.groupby("period")) + [("all", m)]:
        for name, col in (("Always IC 7%", "ic_pnl"), ("Always CS 3%", "cs_pnl"), ("Rule", "rule_pnl")):
            p = g[col]
            out.append(dict(period=period, strategy=name, months=len(p), avg_month=p.mean(),
                            total=p.sum(), losing_months_pct=(p < 0).mean() * 100,
                            worst_month=p.min(), best_month=p.max()))
    return pd.DataFrame(out).round(0).set_index(["period", "strategy"])
