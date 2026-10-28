# src/entry_advisor.py
#
# The single go-to entry list, built to be read twice a day at the 4H candle
# closes without re-deriving any of the reasoning behind it.
#
# Deliberately ENTRY ONLY. Exits are not modelled here: exhaustion_test.py
# found no usable duration-based exit signal, and the conventional rules
# (book at 50% of credit, close at N DTE) have never been tested against this
# data. Wiring in untested exit rules would import folklore into a system that
# has otherwise held itself to a tested standard. Exits stay manual.
#
# Liquidity is deliberately NOT scored or flagged — handled manually.
#
# The filter chain, in order, and why each exists:
#   1. no edge either side  - the signal has never worked on this stock in
#      either direction. The pooled ranking cannot see this because it scores
#      only containment; ALKEM/GRASIM/KOTAKBANK all scored well while being
#      wrong both ways.
#   2. wrong side           - the open direction is the stock's weak half.
#      Freshness is worth nothing when the signal has no edge on that name.
#   3. crash-born flip      - the flip was created by an outlier day, so the
#      containment stats (drawn from ordinary flips) do not describe it. PIIND
#      topped a shortlist on a flip born from a -8.97% fall.
#   4. thin buffer          - spot is close enough to the Supertrend level that
#      an ordinary day could invalidate the trend. NIFTY sat 0.27% away while
#      leading the containment table.
#   5. badly underwater     - the trend is already running against its own
#      entry; the thesis is failing before it is entered.
#   6. weak trend at flip   - ADX(14) on the 4H flip candle was <= 20. Tested in
#      Stage 8g (timeframe_indicator_test.py): 56.5% vs 52.2% wins 2023-26,
#      better on 80% of instruments and in every year, and held on the unused
#      2022 holdout (63.8% vs 59.7%). Skipped flips won only 48.5%. In-sample
#      plus one holdout year, tested WITHOUT the other filters here - adopted
#      2026-10-28 by the user's decision, being checked forward in the journal.
#   7. sector cap           - the concentration gap the README flags as unbuilt.
#   8. 50/50 direction      - so a market-wide shock cannot hit every position.
#
# UNIVERSE (2026-10-28, user's decision, backed by Stage 8i): indices first -
# NIFTY, BANKNIFTY, SENSEX - then NIFTY 50 stocks only. The other ~160 F&O
# stocks reached a 6% strike on a fifth of trades and moved >5% in a day ~26
# times in four years. Indices get their own list (build_index_list): same
# filters 1-5, but NOT the ADX filter - on indices it raised the win rate but
# also the strike-reached rate (1.9 -> 3.1%) and losses over 4%, which is the
# wrong trade for a limited-loss book (Stage 8i). Sector cap and 50/50 do not
# apply there: the three indices move together and are shown as one bet.

import os

import pandas as pd
import pandas_ta as ta

from src.supertrend import load_raw_data

from src.daily_screener import screen_list, split_by_edge, rank_setups
from src.market_context import enrich

MIN_BUFFER_TO_FLIP_PCT = 1.5   # ~1.5 ordinary sessions of room before invalidation
MIN_MOVED_SINCE_ENTRY_PCT = -1.0  # tolerate slight drawdown, not a failing thesis
MAX_PER_SECTOR = 1
MIN_ADX_AT_FLIP = 20.0   # standard trend-strength reading, not tuned (Stage 8g)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX"]
NIFTY50_LIST = os.path.join(PROJECT_ROOT, "config", "nifty50.csv")   # NSE ind_nifty50list.csv
RANKING = os.path.join(PROJECT_ROOT, "exports", "RANKING_credit_spreads.xlsx")


def stock_universe():
    """
    NIFTY 50 members that are gap-risk clean in the credit spread ranking, in
    ranking order. Refresh config/nifty50.csv when NSE rebalances (Mar / Sep):
    https://archives.nseindia.com/content/indices/ind_nifty50list.csv
    """
    members = set(pd.read_csv(NIFTY50_LIST)["Symbol"])
    ranking = pd.read_excel(RANKING)
    clean = ranking[ranking["gap_risk_flag"].isna() | (ranking["gap_risk_flag"] == "")]
    return [s for s in clean["symbol"] if s in members]


def adx_at_flip(symbol, flip_date):
    """
    ADX(14) on the 4H candle that started the current trend - the same value
    the Stage 8g test filtered on. None if the candle isn't in saved data.
    """
    if flip_date is None or pd.isna(flip_date):
        return None
    df = load_raw_data(symbol, "4hour")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    adx = ta.adx(df["high"], df["low"], df["close"], length=14)["ADX_14"]
    adx = adx[adx.index <= pd.Timestamp(flip_date)].dropna()
    return round(float(adx.iloc[-1]), 1) if not adx.empty else None


def _reason(row):
    """
    Plain-language WHY for this specific name, built from its own numbers so
    the list can be acted on without opening the screener.
    """
    is_up = row["direction"] == "UP"
    structure = "BULL PUT" if is_up else "BEAR CALL"
    thesis = "trend is UP, sell puts below" if is_up else "trend is DOWN, sell calls above"

    bits = [
        f"{structure} — {thesis}.",
        f"Flip is {int(row['trend_age_days'])}d old vs a {row['median_duration']}d median.",
        f"{row['direction']} flips here win {row['dir_win_rate']}% "
        f"with a {row['dir_median_move']:+.2f}% median move ({int(row['dir_flips'])} samples).",
        f"{row['contained_6pct']}% of them stayed inside 6% "
        f"(worst {row['worst_adverse']}%).",
        f"Worst gap {row['worst_gap']}%, worst single day {row['worst_day']}%.",
        f"{row['pct_within_30d']}% resolved within 30d.",
    ]
    if pd.notna(row.get("buffer_to_flip_pct")):
        bits.append(f"Spot {row['spot']} sits {row['buffer_to_flip_pct']}% from the "
                    f"{row['flip_level']} flip level.")
    if pd.notna(row.get("moved_since_entry_pct")):
        state = "working" if row["moved_since_entry_pct"] > 0 else "slightly underwater"
        bits.append(f"Trend is {state} ({row['moved_since_entry_pct']:+.2f}% since flip).")
    if pd.notna(row.get("adx_at_flip")):
        bits.append(f"ADX {row['adx_at_flip']} at the flip (> {MIN_ADX_AT_FLIP:g} required).")
    if pd.notna(row.get("beta")):
        bits.append(f"Beta {row['beta']}.")
    if pd.notna(row.get("realized_vol_rank")):
        vol_read = ("elevated" if row["realized_vol_rank"] >= 70
                     else "compressed" if row["realized_vol_rank"] <= 30
                     else "in its normal range")
        bits.append(f"Realized vol {row['realized_vol_pct']}% (annualized), "
                     f"{vol_read} vs its own 2yr history ({row['realized_vol_rank']}th pct — "
                     f"proxy only, not IV, no established threshold yet).")
    return " ".join(bits)


def _suggest_strike(row):
    """
    Strike distance implied by this stock's own containment, expressed off the
    live spot. Uses the 6% band when it held historically, otherwise steps out.
    Descriptive of history, not a recommendation — and it says nothing about
    whether the premium there is worth taking, which needs IV (not built).
    """
    if pd.isna(row.get("spot")):
        return None
    pct = 6.0 if (row.get("contained_6pct") or 0) >= 95 else 7.0
    sign = -1 if row["direction"] == "UP" else 1
    return round(row["spot"] * (1 + sign * pct / 100), 1), pct


def _filter_chain(symbols, min_buffer, min_moved, use_adx):
    """Filters 1-6. Returns (status, surviving pool, excluded)."""
    status = enrich(screen_list(symbols))
    tradeable, watchlist, no_edge = split_by_edge(status)

    excluded = {
        "no_edge_either_side": no_edge["symbol"].tolist(),
        "wrong_side_watchlist": watchlist["symbol"].tolist(),
    }

    pool = tradeable.copy()

    outlier = pool["born_on_outlier_day"].fillna(False).astype(bool)
    excluded["crash_born_flip"] = pool[outlier]["symbol"].tolist()
    pool = pool[~outlier]

    thin = pool["buffer_to_flip_pct"].fillna(0) < min_buffer
    excluded["thin_buffer_to_flip"] = pool[thin]["symbol"].tolist()
    pool = pool[~thin]

    under = pool["moved_since_entry_pct"].fillna(0) < min_moved
    excluded["trend_underwater"] = pool[under]["symbol"].tolist()
    pool = pool[~under]

    # Unknown ADX (flip candle missing from saved data) is excluded too: the
    # tested rule is "take only flips with ADX > 20", not "skip only ADX <= 20".
    pool["adx_at_flip"] = [adx_at_flip(s, d) for s, d in zip(pool["symbol"], pool["flip_date"])]
    if use_adx:
        weak = ~(pd.to_numeric(pool["adx_at_flip"]) > MIN_ADX_AT_FLIP).fillna(False).astype(bool)
        excluded["weak_trend_adx"] = pool[weak]["symbol"].tolist()
        pool = pool[~weak]
    return status, pool, excluded


def build_index_list(min_buffer=MIN_BUFFER_TO_FLIP_PCT, min_moved=MIN_MOVED_SINCE_ENTRY_PCT):
    """
    NIFTY / BANKNIFTY / SENSEX through filters 1-5 (no ADX, no sector cap, no
    50/50 - see header). Returns (final, excluded). Same-direction index picks
    are one correlated bet, not diversification.
    """
    _, pool, excluded = _filter_chain(INDEX_UNIVERSE, min_buffer, min_moved, use_adx=False)
    final = pool.copy()
    if not final.empty:
        final["reason"] = final.apply(_reason, axis=1)
        final = final.sort_values("symbol", key=lambda s: s.map(INDEX_UNIVERSE.index))
    return final.reset_index(drop=True), excluded


def build_entry_list(symbols, n_total=6, min_buffer=MIN_BUFFER_TO_FLIP_PCT,
                        min_moved=MIN_MOVED_SINCE_ENTRY_PCT,
                        max_per_sector=MAX_PER_SECTOR):
    """
    Returns (final_list, excluded, summary).

    Nothing is silently dropped — `excluded` names every symbol removed and the
    stage that removed it, so the list can be trusted without being audited.
    """
    status, pool, excluded = _filter_chain(symbols, min_buffer, min_moved, use_adx=True)
    ranked = rank_setups(pool)

    # 50/50 direction with a sector cap, filled by INTERLEAVING the two sides
    # rather than completing one then the other. Filling UP first lets it claim
    # the shared sectors and starves the DOWN side, which is already the
    # scarcer half — on 2026-08-12 that silently cost the book its balance
    # (DABUR, ITC and ULTRACEMCO were all blocked by UP picks in FMCG and
    # CEMENT, leaving 3 UP against 2 DOWN). Alternating gives neither side
    # first claim, so a sector collision costs whichever candidate is weaker
    # rather than whichever direction happens to be processed first.
    # The sector cap is applied PER DIRECTION, not across the whole book.
    # Concentration risk is about positions that LOSE TOGETHER: two bull puts
    # in FMCG do, but a bull put on NESTLEIND and a bear call on DABUR are
    # opposite bets on the same sector and partially offset. Capping globally
    # treats that hedge as if it were concentration, and — because DOWN-side
    # supply is the scarcer half and spans fewer sectors — it silently costs
    # the book its balance.
    per_side = n_total // 2
    queues = {d: list(ranked[ranked["direction"] == d].iterrows()) for d in ("UP", "DOWN")}
    cursors = {"UP": 0, "DOWN": 0}
    taken = {"UP": 0, "DOWN": 0}
    used_sectors = {"UP": {}, "DOWN": {}}
    picks, dropped_sector = [], []

    while taken["UP"] < per_side or taken["DOWN"] < per_side:
        progressed = False
        for direction in ("DOWN", "UP"):   # scarcer side first within each round
            if taken[direction] >= per_side:
                continue
            queue = queues[direction]
            while cursors[direction] < len(queue):
                _, row = queue[cursors[direction]]
                cursors[direction] += 1
                sec = row.get("sector", "UNKNOWN")
                seen = used_sectors[direction]
                if sec != "UNKNOWN" and seen.get(sec, 0) >= max_per_sector:
                    dropped_sector.append(row["symbol"])
                    continue
                picks.append(row)
                seen[sec] = seen.get(sec, 0) + 1
                taken[direction] += 1
                progressed = True
                break
        if not progressed:
            break   # both sides exhausted
    excluded["sector_cap"] = dropped_sector

    final = pd.DataFrame(picks)
    if not final.empty:
        final["reason"] = final.apply(_reason, axis=1)
        strikes = final.apply(_suggest_strike, axis=1)
        final["short_strike"] = [s[0] if s else None for s in strikes]
        final["strike_buffer_pct"] = [s[1] if s else None for s in strikes]
        final = final.sort_values(["direction", "setup_score"], ascending=[True, False])

    summary = {
        "screened": len(status),
        "selected": len(final),
        "up": int((final["direction"] == "UP").sum()) if not final.empty else 0,
        "down": int((final["direction"] == "DOWN").sum()) if not final.empty else 0,
        "mean_beta_up": round(final[final.direction == "UP"]["beta"].mean(), 2) if not final.empty else None,
        "mean_beta_down": round(final[final.direction == "DOWN"]["beta"].mean(), 2) if not final.empty else None,
        "sectors": sorted(final["sector"].unique().tolist()) if not final.empty else [],
        "supply_up": int((ranked["direction"] == "UP").sum()),
        "supply_down": int((ranked["direction"] == "DOWN").sum()),
    }
    return final, excluded, summary
