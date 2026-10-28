# src/portfolio_compare_test.py
#
# ₹10L book (2023-01 to 2026-10 on resampled 1H, or 2022-01 to 2026-10 on the
# native 4H files with native=True): trade the INDICES only (NIFTY + BANKNIFTY), or
# indices PLUS the NIFTY 50 stocks the list would have picked? (README Stage 8n)
#
# Both books use the live rules:
#   - signal: 4H Supertrend 10,3 flip; exit at the opposite flip or monthly
#     expiry, re-enter after expiry if the trend holds (Stage 8g harness)
#   - indices: 3% OTM short strike, 200-pt hedge (Stage 8l); no ADX filter
#   - stocks: 6% OTM short strike (production default), hedge width 2% of
#     spot (skip-one-strike widths seen live: 1.6-3.8%); ADX(14) > 20 at flip
#   - list filters replayed WALK-FORWARD from each symbol's Flips sheet, using
#     only flips CLOSED before the entry: directional edge (>= 12 flips, win
#     rate >= 50%, median move > 0; fewer flips = unknown = passes, as in
#     production), not crash-born, buffer to the stop >= 1.5%. Re-entries after
#     an expiry get the edge check only. Sector cap / 50-50 / ranking not
#     replayed - this is the filter chain, not the exact daily list.
#   - sizing: lots = floor(₹20,000 / max loss per lot); 0 lots = skipped.
#     Total open max loss capped at 8% (₹80,000): a trade that would breach
#     it is skipped. Current lot sizes for every year.
#   - pricing: Black-Scholes, sigma = India VIX x (60-day realized vol of the
#     underlying / NIFTY's); costs ₹150 per lot at an SL exit, ₹75 at expiry.
#
# Modelled, in-sample, no skew (Stage 8m: the model is ~10% generous at 3% on
# the index; stock option IVs are a VIX proxy, not real). Ranks the two books
# against each other; not a forecast of rupees.

import os
from datetime import datetime, time

import numpy as np
import pandas as pd
import pandas_ta as ta

from src.black_scholes import bs_price, RISK_FREE_RATE
from src.timeframe_indicator_test import load_candles, simulate, monthly_expiries, _st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

CAPITAL, RISK_PER_TRADE, BOOK_CAP = 10_00_000, 20_000, 80_000
INDICES = ["NIFTY", "BANKNIFTY"]
INDEX_PCT, INDEX_WIDTH, INDEX_STEP = 3.0, 200, 100
STOCK_PCT, STOCK_WIDTH_PCT = 6.0, 2.0
COST_SL, COST_EXP = 150, 75
MIN_FLIPS, MIN_WIN, MIN_BUFFER, MIN_ADX = 12, 50.0, 1.5, 20


def _day_close(symbol):
    d = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_day.csv"))
    d.index = pd.to_datetime(d["date"].astype(str).str[:10])
    return d["close"]


def _years(ts, exp):
    return max((datetime.combine(exp, time(15, 30)) - ts.to_pydatetime()).total_seconds(), 0) / (365 * 86400)


def _vertical(S, k, kl, T, sg, opt):
    if T <= 0:
        intrinsic = lambda K: max(0.0, (K - S) if opt == "PE" else (S - K))
        return intrinsic(k) - intrinsic(kl)
    return bs_price(S, k, T, RISK_FREE_RATE, sg, opt) - bs_price(S, kl, T, RISK_FREE_RATE, sg, opt)


def _flips(symbol):
    f = pd.read_excel(os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx"), sheet_name="Flips")
    for col in ("entry_date", "exit_date"):
        f[col] = pd.to_datetime(f[col]).dt.tz_localize(None)
    return f


def _native_4h(symbol):
    """The production 4H file, with candle end times (13:15 candle ends 15:30)."""
    df = pd.read_csv(os.path.join(RAW_DIR, f"{symbol}_4hour.csv"))
    df["date"] = pd.to_datetime(df["date"].astype(str).str[:19])
    df = df.set_index("date")[["open", "high", "low", "close"]]
    close = df.index.normalize() + pd.Timedelta(hours=15, minutes=30)
    df["end"] = np.minimum(df.index + pd.Timedelta(hours=4), close)
    return df


def _passes_filters(flips, t, use_edge=True):
    direction = "UP" if t["up"] else "DOWN"
    prior = flips[(flips["direction"] == direction) & (flips["status"] == "CLOSED")
                  & (flips["exit_date"] < t["entry_time"])]["pct_move"].dropna()
    if use_edge and len(prior) >= MIN_FLIPS and not ((prior > 0).mean() * 100 >= MIN_WIN and prior.median() > 0):
        return False, "no edge"
    row = flips[flips["entry_date"] == t["entry_time"]]
    if not row.empty:                      # a fresh flip, not a post-expiry re-entry
        r = row.iloc[0]
        if pd.notna(r["born_on_outlier_day"]) and bool(r["born_on_outlier_day"]):
            return False, "crash-born"
        if pd.notna(r["initial_sl_pct"]) and r["initial_sl_pct"] < MIN_BUFFER:
            return False, "thin buffer"
    return True, None


def candidate_trades(symbols, lots, vix, nifty_rv, stock_iv_mult=1.0, native=False, use_edge=True):
    rows = []
    for sym in symbols:
        c = _native_4h(sym) if native else load_candles(sym, "4H")
        if len(c) < 1000 or sym not in lots:
            continue
        exp_list = monthly_expiries(c.index.date)
        exp_arr = np.array(exp_list, dtype="datetime64[D]")
        is_index = sym in INDICES
        direction = _st(c, 10, 3)
        ok = None
        if not is_index:
            ok = (ta.adx(c["high"], c["low"], c["close"], length=14)["ADX_14"] > MIN_ADX).fillna(False)
        rv = np.log(_day_close(sym)).diff().rolling(60).std()
        scale = (rv / nifty_rv).shift(1)
        flips = _flips(sym)
        lot = int(lots[sym])
        for t in simulate(c, direction, ok, exp_list, pd.Series(0.2, index=rv.index)):
            passed, why = _passes_filters(flips, t, use_edge)
            if not passed:
                continue
            S0, t0 = c.loc[t["entry_time"], "close"], c.loc[t["entry_time"], "end"]
            S1, t1 = c.loc[t["exit_time"], "close"], c.loc[t["exit_time"], "end"]
            exp = pd.Timestamp(exp_arr[np.searchsorted(exp_arr, np.datetime64(t["entry_time"].date()), "right")]).date()
            up, opt = t["up"], ("PE" if t["up"] else "CE")
            if is_index:
                k = (np.floor(S0 * (1 - INDEX_PCT / 100) / INDEX_STEP) * INDEX_STEP if up
                     else np.ceil(S0 * (1 + INDEX_PCT / 100) / INDEX_STEP) * INDEX_STEP)
                width = INDEX_WIDTH
            else:
                k = S0 * (1 - STOCK_PCT / 100) if up else S0 * (1 + STOCK_PCT / 100)
                width = S0 * STOCK_WIDTH_PCT / 100
            kl = k - width if up else k + width
            sc = 1.0 if sym == "NIFTY" else scale.asof(t["entry_time"].normalize())
            sc = 1.0 if pd.isna(sc) else sc
            if not is_index:
                sc *= stock_iv_mult          # sensitivity: richer stock premiums
            sg0 = vix.asof(t["entry_time"].normalize() - pd.Timedelta(days=1)) / 100 * sc
            sg1 = vix.asof(t["exit_time"].normalize()) / 100 * sc
            credit = _vertical(S0, k, kl, _years(t0, exp), sg0, opt)
            exit_val = _vertical(S1, k, kl, _years(t1, exp), sg1, opt)
            max_loss_lot = (width - credit) * lot
            n = int(RISK_PER_TRADE // max_loss_lot) if max_loss_lot > 0 else 0
            if n == 0:
                continue
            cost = COST_SL if t["reason"] == "SL_HIT" else COST_EXP
            rows.append(dict(symbol=sym, is_index=is_index, entry=t["entry_time"], exit=t["exit_time"],
                             reason=t["reason"], lots=n, max_loss=max_loss_lot * n,
                             credit=credit * lot * n, pnl=((credit - exit_val) * lot - cost) * n))
    return pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)


def run_book(cands, cap=BOOK_CAP):
    """Takes trades in entry order while total open max loss stays within cap."""
    taken, open_ = [], []
    for i, t in cands.iterrows():
        open_ = [o for o in open_ if cands.at[o, "exit"] > t["entry"]]
        if sum(cands.at[o, "max_loss"] for o in open_) + t["max_loss"] > cap:
            continue
        open_.append(i)
        taken.append(i)
    return cands.loc[taken]


def report(book, name, start="2023-01"):
    m = book.groupby(book["exit"].dt.to_period("M"))["pnl"].sum()
    months = pd.period_range(start, book["exit"].max().to_period("M"), freq="M")
    m = m.reindex(months, fill_value=0.0)
    eq = m.cumsum()
    yearly = book.groupby(book["exit"].dt.year)["pnl"].sum()
    return dict(book=name, trades=len(book), total=book["pnl"].sum(),
                per_year_pct=book["pnl"].sum() / CAPITAL * 100 / (len(months) / 12),
                losing_months_pct=(m < 0).mean() * 100, worst_month=m.min(),
                max_drawdown=(eq - eq.cummax()).min(),
                avg_open_risk=None, **{str(y): v for y, v in yearly.items()})


def run(stock_iv_mult=1.0, native=False, use_edge=True):
    lots = pd.read_csv(os.environ["LOTS_CSV"], index_col=0)["lot_size"]
    vix = pd.read_csv(os.path.join(RAW_DIR, "INDIAVIX_day.csv"), index_col=0, parse_dates=True)["close"]
    nifty_rv = np.log(_day_close("NIFTY")).diff().rolling(60).std()
    members = set(pd.read_csv(os.path.join(PROJECT_ROOT, "config", "nifty50.csv"))["Symbol"])
    src = "4hour" if native else "60minute"
    stocks = sorted(s for s in members if os.path.exists(os.path.join(RAW_DIR, f"{s}_{src}.csv"))
                    and os.path.exists(os.path.join(EXPORTS_DIR, f"{s}_full_report.xlsx")))
    cands = candidate_trades(INDICES + stocks, lots, vix, nifty_rv, stock_iv_mult, native, use_edge)
    return cands, run_book(cands[cands["is_index"]]), run_book(cands)
