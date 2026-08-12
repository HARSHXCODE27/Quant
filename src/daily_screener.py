# src/daily_screener.py
import os
import pandas as pd
from datetime import datetime

# Reused rather than re-implemented on purpose. The Flips sheet's `duration`
# column round-trips through Excel as a plain float in days, and calling
# pd.to_timedelta() on that silently collapses everything to ~0 — the exact
# bug reversion_test.py still carries (see README, Stage 8b). Importing
# exhaustion_test.py's already-correct helper avoids writing a third copy
# of this that could drift the same way.
from src.exhaustion_test import _duration_to_days

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

# Minimum same-direction closed flips before a win rate / median move is
# reported at all. Below this the numbers are noise dressed up as a signal,
# so the edge fields come back None and edge_flag says so explicitly rather
# than letting a 6-flip 33% read look like a finding.
MIN_DIRECTIONAL_FLIPS = 12

# Bar for "this side has historically worked": better than a coin flip AND
# a positive median favorable move. Deliberately a plain neutral threshold,
# not an optimised one — nothing here is walk-forward validated (see the
# caveat in _directional_edge), so a tuned cutoff would only be overfitting
# the same four years the ranking already reads.
MIN_WIN_RATE = 50.0


def _directional_edge(flips, direction):
    """
    Per-direction historical behaviour of the Supertrend signal on one stock.

    The credit spread ranking (`score_for_credit_spreads`) is built entirely
    from risk-containment metrics — median/worst adverse, worst gap, duration,
    % within a monthly cycle — pooled across BOTH directions. It contains no
    profitability term at all, so a stock whose UP flips work and whose DOWN
    flips don't scores exactly as well as one where both work, and the
    shortlist gives you no way to tell them apart. This fills that gap.

    Two different questions get answered here, and they are not the same:

      win_rate / median_move  — did the underlying actually move the way the
          signal said? A directional read.
      contained_5pct / _6pct  — did price stay inside a given buffer? This is
          what a credit spread actually needs, since the structure is a
          "won't breach my strike" bet, not a directional one. A stock can
          drift mildly against you and still never threaten a 6% strike.

    Read containment as primary and win rate as a secondary tilt: persistent
    adverse drift means the tail gets tested more often even when it isn't
    breached, which costs you in mark-to-market pressure and forced
    management decisions rather than in outright losses.

    CAVEAT — this is in-sample and descriptive, in the same family as
    past_median/runway_left_* below. It is computed on the same ~4 years of
    flips the ranking itself is built from, with no walk-forward validation
    (unlike the recency-weighting test in Stage 6/7b). It says what this
    signal HAS done on this stock, not what it WILL do. Treat it as a reason
    to look harder at a name, not as a predicted edge.

    Containment uses the Flips sheet's full-flip `max_adverse_pct`, which
    covers the whole trend however long it ran. For a position held to a
    monthly expiry that is conservative — it counts excursions that happened
    after you would already have closed. Capping at 30 days would need the
    raw 4H candles, and this module deliberately reads only exports/.
    """
    same = flips[(flips["direction"] == direction) & (flips["status"] == "CLOSED")]
    if len(same) < MIN_DIRECTIONAL_FLIPS:
        return {"n": len(same)}

    # pct_move is already sign-normalised in flip_analysis.py — for a DOWN
    # flip it is (entry - exit)/entry — so positive always means the trend
    # went the way the signal called it, in both directions.
    move = same["pct_move"].dropna()
    adverse = same["max_adverse_pct"].dropna()
    duration = _duration_to_days(same["duration"].dropna())

    out = {
        "n": len(same),
        "win_rate": round((move > 0).mean() * 100, 1),
        "median_move": round(move.median(), 2),
        "contained_5pct": round((adverse <= 5).mean() * 100, 1),
        "contained_6pct": round((adverse <= 6).mean() * 100, 1),
        "worst_adverse": round(adverse.max(), 2),
        "worst_gap": round(same["max_gap_against_pct"].max(), 2),
        "pct_within_30d": round((duration <= 30).mean() * 100, 1) if len(duration) else None,
    }
    # Present only on reports regenerated since flip_analysis.py started
    # recording it; older exports simply omit the column.
    if "worst_day_against_pct" in same.columns:
        day = same["worst_day_against_pct"].dropna()
        if len(day):
            out["worst_day"] = round(day.max(), 2)
    return out


def _has_edge(edge):
    """
    True only if the side cleared both bars on a large enough sample.

    The bool() cast is load-bearing, not decoration: these values come out of
    pandas as numpy scalars, so the comparison yields numpy.bool_ rather than
    a Python bool, and `numpy.bool_(False) is False` is False. Without the
    cast the `is False` identity checks in _edge_flag silently never match
    and every stock comes back unflagged.
    """
    if edge.get("win_rate") is None:
        return None  # unknown, not False — too few flips to judge either way
    return bool(edge["win_rate"] >= MIN_WIN_RATE and edge["median_move"] > 0)


def _edge_flag(current, opposite):
    """
    Three cases worth separating on a shortlist, because they call for
    different actions:

      NO EDGE EITHER SIDE — neither direction has historically worked on this
          stock. This is the case the ranking is blindest to: the score only
          measures how well-behaved price is, so a stock with tight, gap-free,
          nicely-sized moves and a signal that is wrong both ways scores well
          and looks indistinguishable from a good candidate. Nothing about
          waiting or flipping fixes it — the signal itself doesn't work here.

      weak side — the current direction hasn't worked but the opposite one
          has. Not a bad stock, just the wrong half of it right now. These
          belong on a watchlist for the flip, not in the discard pile.

      "" — the open direction has historically worked.
    """
    cur, opp = _has_edge(current), _has_edge(opposite)

    if current.get("win_rate") is None:
        return f"insufficient history ({current.get('n', 0)} flips this side)"
    if cur is False and opp is False:
        return "⚠ NO EDGE EITHER SIDE — signal has not worked in either direction"
    if cur is False and opp is True:
        return "⚠ weak side — opposite direction is the stronger one, consider waiting for the flip"
    if cur is False:
        return "⚠ weak side — opposite direction has too little history to compare"
    return ""


def check_trend_status(symbol):
    path = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(path):
        print(f"No report found for {symbol}")
        return None

    trades = pd.read_excel(path, sheet_name="Flips")
    summary = pd.read_excel(path, sheet_name="Summary")

    open_trade = trades[trades["status"] == "OPEN"]
    if open_trade.empty:
        return None
    open_trade = open_trade.iloc[0]

    entry_date = pd.to_datetime(open_trade["entry_date"]).tz_localize(None)
    age_days = (datetime.now() - entry_date).days

    def get_metric(name):
        row = summary[summary["metric"] == name]
        return row["value"].values[0] if not row.empty else None

    median_dur = get_metric("Median duration (days)")
    p75_dur = get_metric("75th percentile duration (days)")
    p90_dur = get_metric("90th percentile duration (days)")

    # runway_left_* = checkpoint - age_days: how many more days until this
    # trend's age would reach that percentile of its OWN history, given
    # where it already stands. Purely descriptive, same as past_median/
    # past_75th_pct/past_90th_pct below - NOT a predictive claim. Negative
    # means the trend has already run past that checkpoint (which tested
    # findings show is NOT a reversal warning - see the note below), it
    # just means there's no "runway" left relative to that particular
    # percentile of history. Added because trend_age_days alone tells you
    # how long a trend has run but not how that compares to what's typical
    # in one glance - this makes that comparison direct instead of implicit
    # across three separate booleans, same spirit as the debit-spread/
    # option-buying screeners' candles_left_before_time_exit.
    def runway(checkpoint):
        return round(checkpoint - age_days, 1) if checkpoint is not None else None

    # NOTE: past_median/past_75th_pct/past_90th_pct (and runway_left_*
    # above) are descriptive only - how this trade's age compares to the
    # stock's own history. Tested findings (reversion_test.py,
    # exhaustion_test.py) show crossing these checkpoints does NOT predict
    # an imminent reversal or give a reliable read on remaining time either
    # way - don't read "True" or a negative runway here as a warning or an
    # exit signal.
    # Directional edge for the side that is actually open right now, plus the
    # other side for contrast — a weak current side next to a strong opposite
    # one is a "wait for the flip" name, while weak-on-both is a "the signal
    # doesn't work on this stock" name. See _edge_flag.
    direction = open_trade["direction"]
    opposite = "DOWN" if direction == "UP" else "UP"
    edge = _directional_edge(trades, direction)
    opp_edge = _directional_edge(trades, opposite)

    # The outlier-day warning is APPENDED to edge_flag rather than kept in its
    # own column, so it cannot be missed by anyone reading only the flag — a
    # column alone still requires knowing to look. Appending keeps
    # split_by_edge's prefix matching intact, so bucketing is unaffected: a
    # crash-born flip on a stock with genuine edge still lands in tradeable,
    # it just arrives carrying the warning.
    # bool() cast for the same reason as in _has_edge: this value round-trips
    # through Excel and comes back as a numpy bool, and `numpy.bool_(True) is
    # True` is False, so an identity check here silently never fires.
    edge_flag = _edge_flag(edge, opp_edge)
    born_outlier = open_trade.get("born_on_outlier_day")
    if pd.notna(born_outlier) and bool(born_outlier):
        move = open_trade.get("entry_day_move_pct")
        note = "⚠ flip born on an outlier day"
        if pd.notna(move):
            note += f" ({move:+.2f}% that day)"
        note += " — containment stats come from ordinary flips, they do not describe this"
        edge_flag = f"{edge_flag} | {note}" if edge_flag else note

    return {
        "symbol": symbol,
        "direction": direction,
        "trend_age_days": age_days,
        "median_duration": median_dur,
        "past_median": age_days > median_dur if median_dur else None,
        "past_75th_pct": age_days > p75_dur if p75_dur else None,
        "past_90th_pct": age_days > p90_dur if p90_dur else None,
        "runway_left_vs_median": runway(median_dur),
        "runway_left_vs_p75": runway(p75_dur),
        "runway_left_vs_p90": runway(p90_dur),
        # --- directional edge (this side) ---
        "dir_flips": edge.get("n"),
        "dir_win_rate": edge.get("win_rate"),
        "dir_median_move": edge.get("median_move"),
        "contained_5pct": edge.get("contained_5pct"),
        "contained_6pct": edge.get("contained_6pct"),
        "worst_adverse": edge.get("worst_adverse"),
        "worst_gap": edge.get("worst_gap"),
        "worst_day": edge.get("worst_day"),
        "pct_within_30d": edge.get("pct_within_30d"),
        # Live check on the CURRENTLY OPEN flip: what did price do on the day
        # this trend was born? A flip triggered by a one-day collapse is a
        # different event from an ordinary one, and the containment stats the
        # strike distance is chosen from are drawn from ordinary flips. PIIND
        # topped a shortlist on 2026-08-12 with a flip created that morning by
        # a near-record 8.97% fall — nothing in the screen showed it.
        "entry_day_move": (round(open_trade["entry_day_move_pct"], 2)
                            if "entry_day_move_pct" in open_trade.index
                            and pd.notna(open_trade["entry_day_move_pct"]) else None),
        "born_on_outlier_day": (bool(open_trade["born_on_outlier_day"])
                                if "born_on_outlier_day" in open_trade.index
                                and pd.notna(open_trade["born_on_outlier_day"]) else None),
        # --- the other side, for contrast only ---
        "opp_win_rate": opp_edge.get("win_rate"),
        "opp_median_move": opp_edge.get("median_move"),
        "edge_flag": edge_flag,
    }

def screen_list(symbol_list):
    results = [check_trend_status(s) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])


def rank_setups(candidates):
    """
    Adds a setup_score (0-100) so UP and DOWN candidates can be compared on one
    scale — needed by select_balanced() below, which has to answer "what does
    forcing a bear call in this slot actually cost me?"

    Percentile-ranked within the pool passed in, same helper idea as
    strategy_scoring._pct_rank, weighted toward what a credit spread actually
    depends on:

      contained_6pct  x3  - the strike-distance question, the primary metric
      worst_gap       x2  - unmanageable risk; you cannot trade out of a gap
      worst_day       x2  - the same risk gaps alone were missing
      dir_win_rate    x2  - directional edge
      dir_median_move x1  - size of the typical favourable move

    This is a RELATIVE ordering within today's shortlist, not an absolute
    quality measure — a 90 here means "best of what is on the screen today",
    which in a thin week may still be mediocre. Compare setup_score across
    sides on the same day; do not compare it across days.
    """
    df = candidates.copy()
    if df.empty:
        df["setup_score"] = []
        return df

    def rank(col, lower_is_better):
        if col not in df.columns or df[col].notna().sum() == 0:
            return pd.Series(50.0, index=df.index)  # neutral if unavailable
        r = df[col].rank(pct=True) * 100
        r = (100 - r) if lower_is_better else r
        return r.fillna(50.0)

    df["setup_score"] = (
        rank("contained_6pct", False) * 3 +
        rank("worst_gap", True) * 2 +
        rank("worst_day", True) * 2 +
        rank("dir_win_rate", False) * 2 +
        rank("dir_median_move", False) * 1
    ) / 10
    df["setup_score"] = df["setup_score"].round(1)
    return df.sort_values("setup_score", ascending=False)


def select_balanced(status, n_total=6, exclude_outlier_born=True, min_per_side=None):
    """
    Picks a directionally balanced book — half bull puts (UP flips), half bear
    calls (DOWN flips) — and reports what the balance costs.

    The rationale for balancing is a market-wide shock: in a broad selloff the
    bull puts lose while the bear calls gain, so a 50/50 book cannot have every
    position go against it at once. That much is real. Three things it does NOT
    do, which matter before anyone treats this as a hedge:

      1. It does not hedge VEGA. A crash spikes implied volatility across the
         whole market, and every short-premium position loses on vega
         regardless of direction. The bear calls gain on delta and lose on
         vega at the same time, so the offset is partial.
      2. Balancing COUNT is not balancing RISK. Three spreads on a 25,000-rupee
         stock and three on a 280-rupee stock are not equal exposures. Real
         balance is equal max-loss per side, which needs strike widths and lot
         sizes this module does not have.
      3. It does not account for BETA. A bear call on a defensive FMCG name
         barely moves in a crash while a bull put on a high-beta metal name is
         destroyed. Equal counts, very unequal shock response.

    Returns (picks, report). `report` is a dict describing the trade-off:
    unbalanced_mean/balanced_mean setup_score, the per-side supply, and any
    shortfall — printed rather than silently absorbed, so a forced-in weak
    candidate is a visible decision instead of an invisible one.
    """
    tradeable, _, _ = split_by_edge(status)

    if exclude_outlier_born and "born_on_outlier_day" in tradeable.columns:
        outlier = tradeable["born_on_outlier_day"].fillna(False).astype(bool)
        dropped_outliers = tradeable[outlier]["symbol"].tolist()
        tradeable = tradeable[~outlier]
    else:
        dropped_outliers = []

    ranked = rank_setups(tradeable)
    per_side = n_total // 2 if min_per_side is None else min_per_side

    up = ranked[ranked["direction"] == "UP"]
    down = ranked[ranked["direction"] == "DOWN"]

    picks = pd.concat([up.head(per_side), down.head(per_side)])
    picks = picks.sort_values("setup_score", ascending=False).reset_index(drop=True)

    # What you would have taken with no balance constraint, for comparison.
    unbalanced = ranked.head(len(picks))

    report = {
        "n_requested": n_total,
        "n_selected": len(picks),
        "supply_up": len(up),
        "supply_down": len(down),
        "shortfall_up": max(0, per_side - len(up)),
        "shortfall_down": max(0, per_side - len(down)),
        "excluded_outlier_born": dropped_outliers,
        "unbalanced_mean_score": round(unbalanced["setup_score"].mean(), 1) if len(unbalanced) else None,
        "balanced_mean_score": round(picks["setup_score"].mean(), 1) if len(picks) else None,
    }
    report["cost_of_balance"] = (
        round(report["balanced_mean_score"] - report["unbalanced_mean_score"], 1)
        if report["unbalanced_mean_score"] is not None and report["balanced_mean_score"] is not None
        else None
    )
    report["dropped_for_balance"] = [
        s for s in unbalanced["symbol"].tolist() if s not in picks["symbol"].tolist()
    ]
    return picks, report


def split_by_edge(status):
    """
    Splits a screen_list() frame into the three buckets that call for
    different action, so a no-edge name can't quietly sit next to a good one
    looking the same. Returns (tradeable, watchlist, no_edge).

      tradeable — open direction has historically worked on this stock
      watchlist — wrong side of a stock whose other side works; revisit on flip
      no_edge   — signal hasn't worked either way; the ranking cannot see this

    Nothing is deleted — no_edge is returned, not dropped, so the exclusion is
    visible and auditable rather than silent. Same reasoning as the gap risk
    flag in the scorer, which warns without removing the row.
    """
    flag = status["edge_flag"].fillna("")
    no_edge = status[flag.str.startswith("⚠ NO EDGE")]
    watchlist = status[flag.str.startswith("⚠ weak side")]
    tradeable = status[~status.index.isin(no_edge.index) & ~status.index.isin(watchlist.index)]
    return tradeable, watchlist, no_edge