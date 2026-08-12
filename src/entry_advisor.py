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
#   6. sector cap           - the concentration gap the README flags as unbuilt.
#   7. 50/50 direction      - so a market-wide shock cannot hit every position.

import pandas as pd

from src.daily_screener import screen_list, split_by_edge, rank_setups
from src.market_context import enrich

MIN_BUFFER_TO_FLIP_PCT = 1.5   # ~1.5 ordinary sessions of room before invalidation
MIN_MOVED_SINCE_ENTRY_PCT = -1.0  # tolerate slight drawdown, not a failing thesis
MAX_PER_SECTOR = 1


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
    if pd.notna(row.get("beta")):
        bits.append(f"Beta {row['beta']}.")
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


def build_entry_list(symbols, n_total=6, min_buffer=MIN_BUFFER_TO_FLIP_PCT,
                        min_moved=MIN_MOVED_SINCE_ENTRY_PCT,
                        max_per_sector=MAX_PER_SECTOR):
    """
    Returns (final_list, excluded, summary).

    Nothing is silently dropped — `excluded` names every symbol removed and the
    stage that removed it, so the list can be trusted without being audited.
    """
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
