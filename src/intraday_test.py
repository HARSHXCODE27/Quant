# src/intraday_test.py
#
# Does any popular INTRADAY setup have an edge on this universe? Every trade
# opens and closes the same session - flat by 15:15, nothing carried
# overnight. Stage 8g showed the credit-spread signal degrades on faster
# timeframes; this asks the separate question of whether a same-day system
# works at all (README Stage 8h).
#
# Measured on the UNDERLYING, as % of price - a futures-equivalent trade. An
# options buyer gets the same direction with leverage, theta and a wider
# spread on top, so an edge that is not there on the underlying is not there
# on the option either. Costs are a flat round trip per trade (COST_PCT):
# STT on the futures sell side, exchange/stamp/GST, plus slippage. Gross
# numbers are shown alongside so the cost assumption can be judged.
#
# Setups (standard definitions and parameters, not tuned here):
#   ORB 15 / ORB 30   - opening range = first 15 / 30 min. Enter on the first
#                       5-min CLOSE beyond it (before 14:30), stop = the other
#                       side of the range, exit at the stop, a 2R target (the
#                       "+2R" variants) or 15:15.
#   Gap and go        - gap >= GAP_PCT and the first 15 min closes in the gap's
#                       direction: enter with the gap at 09:30, stop = the
#                       first 15 min's opposite extreme, exit 15:15.
#   Gap fade          - gap >= GAP_PCT: enter AGAINST it at the 09:20 close,
#                       target = previous close (gap filled), stop = one gap
#                       size beyond entry, exit 15:15.
#   VWAP trend        - at the 10:15 close, long if above both VWAP and the
#                       day's open, short if below both. Exit on the first
#                       close back across VWAP, or 15:15. Stocks only: Kite
#                       index candles carry no volume, so no index VWAP.
#   VWAP reversion    - fade a close stretched from VWAP by more than half the
#                       trailing 14-day average daily range (10:00-14:30),
#                       target = touch VWAP, stop = the same distance again,
#                       exit 15:15. Stocks only.
#   Supertrend 10,3 (5m / 15m), EMA 9/21 (15m)
#                     - trade every flip 09:30-14:45 in its direction, exit on
#                       the opposite flip (reverse if still inside the window)
#                       or 15:15.
#
# Fills: entries at candle close; stops/targets at the level, or at the open
# if the candle gapped through it; stop assumed first when a candle hits both.
# In-sample, descriptive - same standard as the rest of the project. The
# 2023-24 vs 2025-26 split is the stability check, not a true holdout.

import os
from datetime import time

import numpy as np
import pandas as pd
import pandas_ta as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")

INDICES = {"NIFTY", "BANKNIFTY"}
COST_PCT = {"index": 0.03, "stock": 0.05}   # round trip, % of price
GAP_PCT = {"index": 0.5, "stock": 1.0}
LAST_ENTRY = time(14, 30)
LAST_FLIP_ENTRY = time(14, 45)
EOD = time(15, 10)                           # the 15:10 candle closes at 15:15


def load_5min(symbol):
    df = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_5minute.csv"), parse_dates=["date"])
    df["day"] = df["date"].dt.date
    df["t"] = df["date"].dt.time
    full = df.groupby("day")["t"].transform("size") >= 70   # drops muhurat / half sessions
    return df[full].reset_index(drop=True)


def resample_15(df):
    g = df.set_index("date").resample("15min", origin="start_day", offset="15min")
    out = g.agg({"open": "first", "high": "max", "low": "min", "close": "last",
                 "volume": "sum"}).dropna().reset_index()
    out["day"] = out["date"].dt.date
    out["t"] = out["date"].dt.time
    return out


def _walk(o, h, l, c, i, last, d, entry, stop=None, target=None, exit_flag=None):
    """Exit price of a trade entered at close i, direction d (+1/-1)."""
    for j in range(i + 1, last + 1):
        if stop is not None and ((d > 0 and l[j] <= stop) or (d < 0 and h[j] >= stop)):
            return (min(o[j], stop) if d > 0 else max(o[j], stop)), j
        if target is not None and ((d > 0 and h[j] >= target) or (d < 0 and l[j] <= target)):
            return (max(o[j], target) if d > 0 else min(o[j], target)), j
        if exit_flag is not None and exit_flag[j]:
            return c[j], j
    return c[last], last


def _trade(name, day, d, entry, exit_):
    return dict(setup=name, day=day, dir=d, gross=d * (exit_ - entry) / entry * 100)


def _day_slices(df):
    return [(day, idx.values) for day, idx in df.groupby("day").groups.items()]


def opening_range(df, minutes, target_r=None):
    name = f"ORB {minutes}" + (f" +{target_r:g}R" if target_r else "")
    o, h, l, c, t = (df[k].values for k in ("open", "high", "low", "close", "t"))
    n_range = minutes // 5
    out = []
    for day, idx in _day_slices(df):
        hi, lo = h[idx[:n_range]].max(), l[idx[:n_range]].min()
        last = idx[[tt == EOD for tt in t[idx]]]
        if not len(last):
            continue
        last = last[0]
        for i in idx[n_range:]:
            if t[i] > LAST_ENTRY:
                break
            d = 1 if c[i] > hi else -1 if c[i] < lo else 0
            if d:
                stop = lo if d > 0 else hi
                tgt = c[i] + d * target_r * abs(c[i] - stop) if target_r else None
                px, _ = _walk(o, h, l, c, i, last, d, c[i], stop, tgt)
                out.append(_trade(name, day, d, c[i], px))
                break
    return out


def gaps(df, gap_pct):
    o, h, l, c, t = (df[k].values for k in ("open", "high", "low", "close", "t"))
    out, prev_close = [], None
    for day, idx in _day_slices(df):
        last = idx[[tt == EOD for tt in t[idx]]]
        if prev_close is None or not len(last):
            prev_close = c[idx[-1]]
            continue
        last = last[0]
        gap = (o[idx[0]] - prev_close) / prev_close * 100
        if abs(gap) >= gap_pct:
            g = 1 if gap > 0 else -1
            # gap and go: first 15 min (3 candles) closes in the gap direction
            i = idx[2]
            if g * (c[i] - o[idx[0]]) > 0:
                stop = l[idx[:3]].min() if g > 0 else h[idx[:3]].max()
                px, _ = _walk(o, h, l, c, i, last, g, c[i], stop)
                out.append(_trade("Gap and go", day, g, c[i], px))
            # gap fade: against the gap from the 09:20 close, target the fill
            i = idx[0]
            d = -g
            stop = c[i] + g * abs(o[idx[0]] - prev_close)
            px, _ = _walk(o, h, l, c, i, last, d, c[i], stop, prev_close)
            out.append(_trade("Gap fade", day, d, c[i], px))
        prev_close = c[idx[-1]]
    return out


def _vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).groupby(df["day"]).cumsum()
    v = df["volume"].groupby(df["day"]).cumsum()
    return (pv / v.replace(0, np.nan)).values


def vwap_setups(df):
    o, h, l, c, t = (df[k].values for k in ("open", "high", "low", "close", "t"))
    vw = _vwap(df)
    daily = df.groupby("day").agg(hi=("high", "max"), lo=("low", "min"), cl=("close", "last"))
    rng = ((daily["hi"] - daily["lo"]) / daily["cl"] * 100).rolling(14).mean().shift(1)
    out = []
    for day, idx in _day_slices(df):
        last = idx[[tt == EOD for tt in t[idx]]]
        if not len(last) or np.isnan(vw[idx]).any():
            continue
        last = last[0]
        # trend: the 10:15 close vs VWAP and the open
        i = idx[[tt == time(10, 15) for tt in t[idx]]]
        if len(i):
            i = i[0]
            d = (1 if c[i] > vw[i] and c[i] > o[idx[0]] else
                 -1 if c[i] < vw[i] and c[i] < o[idx[0]] else 0)
            if d:
                crossed = np.zeros(len(c), bool)
                crossed[idx] = (c[idx] < vw[idx]) if d > 0 else (c[idx] > vw[idx])
                px, _ = _walk(o, h, l, c, i, last, d, c[i], exit_flag=crossed)
                out.append(_trade("VWAP trend", day, d, c[i], px))
        # reversion: stretched by > half the average daily range
        band = rng.get(day, np.nan) / 2
        if np.isnan(band):
            continue
        for i in idx:
            if t[i] < time(10, 0):
                continue
            if t[i] > LAST_ENTRY:
                break
            dev = (c[i] - vw[i]) / vw[i] * 100
            if abs(dev) > band:
                d = -1 if dev > 0 else 1
                dist = abs(c[i] - vw[i])
                px, _ = _walk(o, h, l, c, i, last, d, c[i], c[i] - d * dist, vw[i])
                out.append(_trade("VWAP reversion", day, d, c[i], px))
                break
    return out


def flip_system(df, direction, name, eod=EOD):
    """Trade every flip inside the window; exit on the next flip or 15:15.
    eod = the START time of the candle that closes at 15:15 (15:00 on 15m)."""
    o, h, l, c, t = (df[k].values for k in ("open", "high", "low", "close", "t"))
    dirs = direction.values
    out = []
    for day, idx in _day_slices(df):
        last = idx[[tt == eod for tt in t[idx]]]
        if not len(last):
            continue
        last = last[0]
        pos = None
        for i in idx:
            if i == 0 or np.isnan(dirs[i]) or np.isnan(dirs[i - 1]) or i > last:
                continue
            flipped = dirs[i] != dirs[i - 1]
            if pos and flipped:
                out.append(_trade(name, day, pos[0], pos[1], c[i]))
                pos = None
            if pos is None and flipped and time(9, 30) <= t[i] <= LAST_FLIP_ENTRY:
                pos = (int(dirs[i]), c[i])
        if pos:
            out.append(_trade(name, day, pos[0], pos[1], c[last]))
    return out


def _st_dir(df, length=10, mult=3.0):
    st = ta.supertrend(df["high"], df["low"], df["close"], length=length, multiplier=mult)
    return st[f"SUPERTd_{length}_{mult}"]


def _ema_dir(df, fast=9, slow=21):
    f, s = ta.ema(df["close"], fast), ta.ema(df["close"], slow)
    return pd.Series(np.where(f > s, 1.0, -1.0), index=df.index).where(s.notna())


def run_symbol(symbol):
    kind = "index" if symbol in INDICES else "stock"
    m5 = load_5min(symbol)
    m15 = resample_15(m5)
    m15 = m15[m15.groupby("day")["t"].transform("size") >= 25].reset_index(drop=True)
    rows = []
    for mins in (15, 30):
        rows += opening_range(m5, mins)
        rows += opening_range(m5, mins, target_r=2)
    rows += gaps(m5, GAP_PCT[kind])
    if kind == "stock":
        rows += vwap_setups(m5)
    rows += flip_system(m5, _st_dir(m5), "Supertrend 10,3 (5m)")
    rows += flip_system(m15, _st_dir(m15), "Supertrend 10,3 (15m)", eod=time(15, 0))
    rows += flip_system(m15, _ema_dir(m15), "EMA 9/21 (15m)", eod=time(15, 0))
    out = pd.DataFrame(rows)
    out["symbol"], out["kind"] = symbol, kind
    out["net"] = out["gross"] - COST_PCT[kind]
    out["year"] = pd.to_datetime(out["day"]).dt.year
    return out


def summarize(trades, by=("setup",)):
    """Pooled trade stats plus per-instrument breadth and the two-half check."""
    t = trades.copy()
    t["win"] = t["net"] > 0
    t["half"] = np.where(t["year"] <= 2024, "2023-24", "2025-26")
    by = list(by)
    pooled = t.groupby(by).agg(
        instruments=("symbol", "nunique"), trades=("net", "size"),
        win_rate=("win", "mean"), avg_gross=("gross", "mean"), avg_net=("net", "mean"),
        pf_net=("net", lambda s: s[s > 0].sum() / -s[s < 0].sum() if (s < 0).any() else np.nan),
    )
    per_inst = t.groupby(by + ["symbol"])["net"].mean().gt(0).groupby(by).mean()
    halves = t.groupby(by + ["half"])["net"].mean().unstack("half")
    months = t.groupby("symbol")["day"].agg(lambda d: (max(d) - min(d)).days / 30.44)
    per_month = (t.groupby(by + ["symbol"]).size() / t.groupby(by + ["symbol"])["symbol"]
                 .first().map(months).values).groupby(by).median()
    out = pooled.assign(pct_instruments_positive=per_inst * 100,
                        trades_per_month=per_month,
                        net_2023_24=halves.get("2023-24"),
                        net_2025_26=halves.get("2025-26"))
    out["win_rate"] *= 100
    return out.round(3).sort_values("avg_net", ascending=False)
