# src/spread_builder.py
#
# Turns a list pick (symbol + direction) into an actual hedged spread with
# live prices, and sizes it by MAXIMUM LOSS. Read-only: uses kite.quote() and
# kite.basket_order_margins() (a margin CALCULATOR - nothing is ordered).
#
# The user's own rules, as given 2026-10-28:
#   - capital ₹10L, max loss per trade 1-2% of it (MAX_LOSS_PCT is the cap)
#   - hedge: skip one liquid strike and buy the next (sold 1240 CE, skipped
#     1260, bought 1280) -> long = short +/- 2 strike steps
#   - indices: short strike = first listed strike at or beyond 3% from spot
#     (2026-10-29, TRADING_RULES.md). Replaced "farthest strike paying 1.5% on
#     margin": that landed ~5% out, where costs ate the credit (Stage 8l: 3%
#     netted +₹115/lot before costs vs +₹19 at 5%). Return on margin is still shown.
#   - stocks: short strike stays the containment-based 6/7% (entry_advisor)
#
# "Return" = credit / margin blocked (Kite's own spread margin, hedge benefit
# included). That is how sellers quote it; it is NOT % of the ₹10L.
#
# Credit is priced conservatively: short leg at the BID, long leg at the ASK
# (what a market order would get). Off-hours the book is often empty, so it
# falls back to last traded prices and says so in quote_basis.
#
# hist_strike_reach_pct (indices) is how often price reached a short strike
# that far away before the Supertrend exit or expiry - NIFTY/BANKNIFTY/SENSEX,
# 2023-26, Stage 8i. In-sample, descriptive. Nothing here filters on it.

import math
import time

import numpy as np
import pandas as pd

CAPITAL = 10_00_000
MAX_LOSS_PCT = 2.0                  # of CAPITAL, per trade (user: 1-2%)
INDEX_STRIKE_PCT = 3.0              # index short strike distance (Stage 8l)
HEDGE_SKIP_STEPS = 2                # short +/- 2 steps: skip one, buy the next
INDEX_STEP = {"NIFTY": 100, "BANKNIFTY": 100, "SENSEX": 100}   # liquid strike grid
OPTION_EXCHANGE = {"SENSEX": "BFO"}                             # default NFO

# Stage 8i: % of trades whose short strike at this distance was reached
# (NIFTY + BANKNIFTY + SENSEX, 4H Supertrend 10,3, journal rules, 2023-26).
INDEX_STRIKE_REACH = {2: 23.2, 3: 9.0, 4: 5.1, 5: 3.2, 6: 1.9}


def option_chain(kite, cache=None):
    """name -> DataFrame of that underlying's CE/PE contracts, NFO + BFO."""
    if cache:
        return cache
    frames = []
    for ex in ("NFO", "BFO"):
        df = pd.DataFrame(kite.instruments(ex))
        frames.append(df[df["instrument_type"].isin(["CE", "PE"])].assign(exchange=ex))
    opts = pd.concat(frames, ignore_index=True)
    opts["expiry"] = pd.to_datetime(opts["expiry"]).dt.date
    return {name: g for name, g in opts.groupby("name")}


def monthly_expiries(chain):
    """name -> sorted monthly expiries (last listed expiry of each month)."""
    out = {}
    for name, g in chain.items():
        ym = g["expiry"].map(lambda d: (d.year, d.month))
        out[name] = sorted(g.groupby(ym)["expiry"].max().tolist())
    return out


def _reach_pct(distance_pct):
    keys = sorted(INDEX_STRIKE_REACH)
    if distance_pct <= keys[0]:
        return INDEX_STRIKE_REACH[keys[0]]
    if distance_pct >= keys[-1]:
        return INDEX_STRIKE_REACH[keys[-1]]
    return round(float(np.interp(distance_pct, keys, [INDEX_STRIKE_REACH[k] for k in keys])), 1)


def _prices(kite, contracts):
    """tradingsymbol -> (bid, ask, last). One quote call for all contracts."""
    keys = [f"{r.exchange}:{r.tradingsymbol}" for r in contracts.itertuples()]
    out = {}
    for i in range(0, len(keys), 400):
        for key, q in kite.quote(keys[i:i + 400]).items():
            buy, sell = q.get("depth", {}).get("buy", []), q.get("depth", {}).get("sell", [])
            bid = buy[0]["price"] if buy and buy[0]["price"] > 0 else None
            ask = sell[0]["price"] if sell and sell[0]["price"] > 0 else None
            out[key.split(":", 1)[1]] = (bid, ask, q.get("last_price"))
    return out


def _credit(px, short_sym, long_sym):
    sb, _, sl = px.get(short_sym, (None, None, None))
    _, la, ll = px.get(long_sym, (None, None, None))
    if sb is not None and la is not None:
        return sb - la, "bid/ask"
    if sl is not None and ll is not None:
        return sl - ll, "last traded (book empty)"
    return None, "no quote"


def _margin(kite, exchange, short_sym, long_sym, qty):
    leg = dict(exchange=exchange, variety="regular", product="NRML",
               order_type="MARKET", quantity=int(qty), price=0)
    m = kite.basket_order_margins(
        [dict(leg, tradingsymbol=long_sym, transaction_type="BUY"),     # hedge first
         dict(leg, tradingsymbol=short_sym, transaction_type="SELL")],
        consider_positions=False, mode="compact")
    time.sleep(0.2)
    return float(m["final"]["total"])


def _strike_grid(contracts, step=None):
    strikes = np.sort(contracts["strike"].unique())
    if step:
        strikes = strikes[np.isclose(strikes % step, 0)]
    return strikes


def _sized(row, short_k, long_k, credit, basis, margin, lot):
    width = abs(short_k - long_k)
    max_loss_lot = (width - credit) * lot
    budget = CAPITAL * MAX_LOSS_PCT / 100
    lots = int(budget // max_loss_lot) if max_loss_lot > 0 else 0
    spot = row["spot"]
    return dict(
        short_strike=float(short_k), long_strike=float(long_k), width=float(width),
        strike_distance_pct=round(abs(spot - short_k) / spot * 100, 2),
        credit=round(credit, 2), quote_basis=basis, lot_size=int(lot),
        margin_per_lot=round(margin), return_on_margin_pct=round(credit * lot / margin * 100, 2),
        max_loss_per_lot=round(max_loss_lot), lots=lots,
        max_loss_total=round(max_loss_lot * lots), credit_total=round(credit * lot * lots),
        lot_too_big=lots == 0,
        # strike sits between spot and the Supertrend stop: price can reach the
        # strike without the stop having fired first. Information only.
        strike_inside_sl=bool((short_k > row["flip_level"]) if row["direction"] == "UP"
                              else (short_k < row["flip_level"])),
    )


def build_spread(kite, row, chain, expiry, is_index):
    """
    One pick -> dict of spread fields (see _sized), or {"spread_problem": why}.
    row needs symbol, direction, spot, flip_level (and short_strike for stocks).
    """
    sym, up = row["symbol"], row["direction"] == "UP"
    opt = "PE" if up else "CE"
    c = chain.get(sym)
    if c is None or expiry is None:
        return {"spread_problem": "no option contracts / expiry found"}
    c = c[(c["expiry"] == expiry) & (c["instrument_type"] == opt)]
    if c.empty:
        return {"spread_problem": f"no {opt} contracts for {expiry}"}
    lot = int(c["lot_size"].iloc[0])
    exchange = c["exchange"].iloc[0]
    by_strike = c.set_index("strike")["tradingsymbol"]
    grid = _strike_grid(c, INDEX_STEP.get(sym) if is_index else None)
    spot = row["spot"]
    sign = -1 if up else 1              # OTM side: below spot for puts, above for calls

    if is_index:
        # first listed strike at or beyond INDEX_STRIKE_PCT from spot (Stage 8l)
        target = spot * (1 + sign * INDEX_STRIKE_PCT / 100)
    else:
        target = row.get("short_strike")
        if target is None or pd.isna(target):
            return {"spread_problem": "no suggested strike"}
    # first listed strike at or beyond the target (further OTM)
    beyond = grid[grid <= target] if up else grid[grid >= target]
    if not len(beyond):
        return {"spread_problem": "target strike outside the listed range"}
    short_k = beyond.max() if up else beyond.min()
    j = np.searchsorted(grid, short_k) + sign * HEDGE_SKIP_STEPS
    if not 0 <= j < len(grid):
        return {"spread_problem": "no hedge strike listed"}
    long_k = grid[j]
    legs = c[c["strike"].isin([short_k, long_k])]
    credit, basis = _credit(_prices(kite, legs), by_strike[short_k], by_strike[long_k])
    if credit is None or credit <= 0:
        return {"spread_problem": f"no positive credit ({basis})"}
    margin = _margin(kite, exchange, by_strike[short_k], by_strike[long_k], lot)
    out = _sized(row, short_k, long_k, credit, basis, margin, lot)
    if is_index:
        out["hist_strike_reach_pct"] = _reach_pct(out["strike_distance_pct"])

    out.update(option_exchange=exchange, expiry=str(expiry),
               short_symbol=by_strike[out["short_strike"]],
               long_symbol=by_strike[out["long_strike"]])
    return out


def add_spreads(kite, final, index_symbols, today=None):
    """Adds spread + sizing columns to a final list (stocks and/or indices)."""
    if final is None or final.empty:
        return final
    from src.credit_spread_journal import current_month_expiry
    chain = option_chain(kite)
    expiries = monthly_expiries(chain)
    rows = []
    for _, r in final.iterrows():
        try:
            exp = current_month_expiry(r["symbol"], expiries, today)
            rows.append(build_spread(kite, r, chain, exp, r["symbol"] in index_symbols))
        except Exception as e:
            rows.append({"spread_problem": str(e)})
    spreads = pd.DataFrame(rows, index=final.index)
    # build_spread's short_strike is the real listed strike; keep the
    # containment-based suggestion as suggested_strike for stocks
    out = final.rename(columns={"short_strike": "suggested_strike"})
    return pd.concat([out, spreads], axis=1)


def risk_summary(final):
    """Total max loss / credit / margin across the book, in ₹ and % of capital."""
    if final is None or final.empty or "max_loss_total" not in final:
        return {}
    lots = final["lots"].fillna(0)
    margin = (final["margin_per_lot"].fillna(0) * lots).sum()
    loss = final["max_loss_total"].fillna(0).sum()
    return dict(positions=int((lots > 0).sum()), max_loss=round(loss),
                max_loss_pct=round(loss / CAPITAL * 100, 1),
                credit=round(final["credit_total"].fillna(0).sum()),
                margin=round(margin), margin_pct=round(margin / CAPITAL * 100, 1))


def vix_context(kite):
    """
    India VIX now and its percentile vs the trailing year (252 sessions).
    Context only, not a filter - Stage 8j: in the top third, index trades
    moved beyond VIX's own implied 1-SD range 2.4x as often as in the bottom
    third (13.4% vs 5.5%) with larger losses; the extra premium did not make
    up for it. One test, 311 trades, in-sample.
    """
    from datetime import datetime, timedelta
    from src.instruments import get_index_token
    tok = get_index_token(kite, "INDIA VIX", "NSE")
    d = pd.DataFrame(kite.historical_data(tok, datetime.now() - timedelta(days=400),
                                          datetime.now(), "day"))
    closes = d["close"].tail(253)
    now = float(closes.iloc[-1])
    pct = round(float((closes.iloc[:-1] < now).mean() * 100))
    regime = "LOW" if pct <= 33 else "HIGH" if pct > 66 else "MIDDLE"
    return dict(vix=round(now, 2), vix_pctile=pct, vix_regime=regime)

