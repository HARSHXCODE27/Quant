# src/position_monitor.py
#
# Reads currently open F&O option positions directly from Kite — no manual
# ledger. What structure you're in is inferred from the legs themselves: a
# net-short CE implies a bear call (thesis = DOWN), a net-short PE implies a
# bull put (thesis = UP). That inferred thesis is then checked against
# daily_screener.check_trend_status() for the SAME underlying — the exact
# same tested logic the entry screener itself uses, not a new rule. If the
# live flip direction no longer matches what the position implies, the
# reason the position was opened no longer holds.
#
# Deliberately does NOT add a profit-target or DTE-based exit rule — those
# have never been tested against this data (see README, exhaustion_test
# finding) and stay out of scope here. This only answers "does the entry
# thesis still hold," reusing already-validated columns and the same
# MIN_BUFFER_TO_FLIP_PCT cutoff the entry screener already applies.

import pandas as pd

from src.daily_screener import check_trend_status
from src.market_context import enrich
from src.entry_advisor import MIN_BUFFER_TO_FLIP_PCT


def _option_instrument_lookup(kite):
    instruments = pd.DataFrame(kite.instruments("NFO"))
    options = instruments[instruments["instrument_type"].isin(["CE", "PE"])]
    return options.set_index("instrument_token")[["name", "expiry", "strike", "instrument_type"]]


def get_open_option_positions(kite):
    """
    Currently open (non-zero quantity) NFO option legs, enriched with
    underlying name/expiry/strike/type from the instrument dump. One row per
    leg — grouping into per-underlying theses happens in build_position_report.
    """
    positions = kite.positions()["net"]
    df = pd.DataFrame(positions)
    if df.empty:
        return df
    df = df[(df["exchange"] == "NFO") & (df["quantity"] != 0)]
    if df.empty:
        return df

    lookup = _option_instrument_lookup(kite)
    df = df.join(lookup, on="instrument_token")
    return df[df["instrument_type"].isin(["CE", "PE"])]


def _infer_thesis(legs):
    """
    Any short CE leg implies a bear call (bet: won't rise above strike,
    thesis DOWN). Any short PE leg implies a bull put (bet: won't fall below
    strike, thesis UP). Checked per-leg with .any(), NOT by summing quantity
    within each option type first — a real defined-risk vertical (short the
    near strike, long a further strike of the SAME type as protection) has
    quantities that cancel to zero on sum, which would wrongly read as no
    position at all. Short legs on both CE and PE at once (e.g. an iron
    condor) has no single directional thesis to check against — reported,
    not flagged.
    """
    ce = legs[legs["instrument_type"] == "CE"]
    pe = legs[legs["instrument_type"] == "PE"]
    short_ce = (ce["quantity"] < 0).any()
    short_pe = (pe["quantity"] < 0).any()

    if short_ce and not short_pe:
        return "DOWN", "BEAR CALL"
    if short_pe and not short_ce:
        return "UP", "BULL PUT"
    if short_ce and short_pe:
        return None, "MIXED / NON-DIRECTIONAL (short both sides)"
    return None, "LONG OPTIONS ONLY / NON-DIRECTIONAL"


def build_position_report(kite):
    """
    One row per underlying currently held via NFO options. Live P&L comes
    straight from Kite (not modelled — this project has no IV/option pricing
    data, see README's open IV-rank gap). thesis_status compares the
    inferred entry direction against the CURRENT screener state for that
    underlying, so a reversed flip or a name that's slid into watchlist/
    no_edge since entry is impossible to miss.
    """
    legs = get_open_option_positions(kite)
    if legs.empty:
        return pd.DataFrame()

    rows = []
    for name, group in legs.groupby("name"):
        thesis_direction, structure = _infer_thesis(group)
        expiry = group["expiry"].iloc[0]
        dte = (pd.to_datetime(expiry) - pd.Timestamp.now().normalize()).days

        # short_qty/long_qty rather than a net sum — a real defined-risk
        # vertical (short one strike, long another of the same type as
        # protection) sums to zero and would misleadingly read as no position.
        short_qty = int(-group.loc[group["quantity"] < 0, "quantity"].sum())
        long_qty = int(group.loc[group["quantity"] > 0, "quantity"].sum())
        row = {
            "symbol": name,
            "structure": structure,
            "legs": len(group),
            "short_qty": short_qty,
            "long_qty": long_qty,
            "live_pnl": round(group["pnl"].sum(), 2),
            "expiry": expiry.date() if hasattr(expiry, "date") else expiry,
            "dte": dte,
        }

        status = check_trend_status(name)
        if status is None:
            row["current_direction"] = None
            row["thesis_status"] = "⚠ no open flip in this symbol's report — refresh its data first"
            rows.append(row)
            continue

        enriched = enrich(pd.DataFrame([status])).iloc[0]
        row["current_direction"] = status["direction"]
        row["trend_age_days"] = status["trend_age_days"]
        row["buffer_to_flip_pct"] = enriched.get("buffer_to_flip_pct")
        row["moved_since_entry_pct"] = enriched.get("moved_since_entry_pct")
        row["edge_flag"] = status["edge_flag"]

        notes = []
        if thesis_direction is None:
            notes.append("non-directional position, nothing to compare")
        elif status["direction"] != thesis_direction:
            notes.append(
                f"⚠ FLIP REVERSED — entered on {thesis_direction}, now "
                f"{status['direction']} ({status['trend_age_days']}d old)"
            )
        else:
            if status["edge_flag"].startswith("⚠ NO EDGE") or status["edge_flag"].startswith("⚠ weak side"):
                notes.append(f"⚠ signal weakened since entry — {status['edge_flag']}")
            buf = enriched.get("buffer_to_flip_pct")
            if pd.notna(buf) and buf < MIN_BUFFER_TO_FLIP_PCT:
                notes.append(f"⚠ buffer to flip now {buf}% — thinner than the {MIN_BUFFER_TO_FLIP_PCT}% entry cutoff")
            if not notes:
                notes.append("thesis intact")

        row["thesis_status"] = " | ".join(notes)
        rows.append(row)

    return pd.DataFrame(rows)
