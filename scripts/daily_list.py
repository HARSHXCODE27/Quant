#!/usr/bin/env python3
"""
The twice-a-day go-to entry list.

Run after each 4H candle close — 13:20 and 15:35 IST. There are only two 4H
candles per session (09:15 and 13:15), so Supertrend, flips and every signal
downstream change exactly twice a day. Running more often re-prints identical
output and burns API calls for nothing.

    python scripts/daily_list.py                # refresh + build list
    python scripts/daily_list.py --no-refresh   # rebuild from saved data only
    python scripts/daily_list.py --n 8          # smaller book

Two lists: INDICES first (NIFTY, BANKNIFTY, SENSEX), then NIFTY 50 stocks
only (Stage 8i). With a live token each pick becomes a real hedged spread -
listed strikes, live credit, Kite's margin, lots sized so max loss stays
within the per-trade cap (src/spread_builder.py).

Writes reports/YYYY-MM-DD_HHMM_entry_list.md and prints the same to stdout.

Requires a valid Kite token unless --no-refresh is passed. Tokens expire
overnight, so run scripts/refresh_token.py once each morning first.
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")


def shortlist_symbols(top_n=None):
    """NIFTY 50 stocks (gap-clean, ranking order) + the index universe."""
    from src.entry_advisor import stock_universe, INDEX_UNIVERSE
    return list(dict.fromkeys(stock_universe()[:top_n] + INDEX_UNIVERSE))


def refresh(symbols):
    """Incremental candle catch-up for the shortlist only. The one API step."""
    from src.auth import get_kite
    from src.instruments import build_nse_token_lookup, get_index_token, INDEX_SYMBOLS
    from src.scale_pipeline import process_stock_incremental

    kite = get_kite()
    lookup = build_nse_token_lookup(kite)
    index_symbols = INDEX_SYMBOLS

    failed = []
    for i, symbol in enumerate(symbols, start=1):
        try:
            if symbol in index_symbols:
                ts, ex = index_symbols[symbol]
                token = get_index_token(kite, ts, ex)
            else:
                token = lookup.get(symbol)
            if token is None:
                failed.append(f"{symbol}: no token")
                continue
            process_stock_incremental(symbol, token, kite, to_date=datetime.now())
        except Exception as e:
            failed.append(f"{symbol}: {e}")
    return failed


def _spread_line(r):
    """One line describing the actual spread, or why there isn't one."""
    if "lots" not in r or pd.isna(r.get("lots")):
        if pd.notna(r.get("spread_problem")) if "spread_problem" in r else False:
            return f"- ⚠ **No spread:** {r['spread_problem']}"
        return "- *Spread not priced (run with a live token)*"
    opt = "PE" if r["direction"] == "UP" else "CE"
    line = (f"- **Sell {r['short_strike']:,.0f} {opt} / buy {r['long_strike']:,.0f} {opt}**, "
            f"exp {r['expiry']} ({_dte(r)}d) · {r['strike_distance_pct']}% OTM · "
            f"credit {r['credit']} ({r['quote_basis']}) · "
            f"{int(r['lots'])} lot(s) × {int(r['lot_size'])} · "
            f"max loss ₹{r['max_loss_total']:,.0f} · credit ₹{r['credit_total']:,.0f} · "
            f"margin ₹{r['margin_per_lot'] * r['lots']:,.0f} · "
            f"return on margin {r['return_on_margin_pct']}%")
    notes = []
    if bool(r.get("lot_too_big", False)):
        notes.append(f"one lot's max loss ₹{r['max_loss_per_lot']:,.0f} is over the cap — skip")
    if pd.notna(r.get("hist_strike_reach_pct")):
        notes.append(f"strikes this far were reached {r['hist_strike_reach_pct']}% of the time (Stage 8i)")
    if bool(r.get("strike_inside_sl", False)):
        notes.append("strike is CLOSER than the Supertrend stop — price can reach it before the stop fires")
    if _dte(r) <= 7:
        notes.append(f"expires in {_dte(r)} days")
    return line + ("".join(f"\n  - {n}" for n in notes))


def VIX_LINE(risk):
    return (f"India VIX {risk['vix']} — {risk['vix_pctile']}th percentile of the past year "
            f"({risk['vix_regime']})")


def _dte(r):
    return (pd.Timestamp(r["expiry"]).date() - datetime.now().date()).days


def render(final, excluded, summary, refresh_errors, index_final=None, index_excluded=None,
           risk=None):
    now = datetime.now()
    L = [f"# Entry list — {now:%Y-%m-%d %H:%M}", ""]

    if refresh_errors:
        L += ["## ⚠ Refresh problems", ""] + [f"- {e}" for e in refresh_errors] + [""]

    if risk:
        L += [f"**Book if all taken:** max loss ₹{risk['max_loss']:,} "
              f"({risk['max_loss_pct']}% of capital) · credit ₹{risk['credit']:,} · "
              f"margin ₹{risk['margin']:,} ({risk['margin_pct']}%) · "
              f"{risk['positions']} position(s)", ""]

    if risk and "vix" in risk:
        L += [f"**{VIX_LINE(risk)}**" + (" — in the top third, index trades broke VIX's implied range "
              "2.4× as often and lost more (Stage 8j). Context, not a filter." if risk["vix_regime"] == "HIGH" else ""), ""]
    L += ["## Indices", ""]
    if index_final is None or index_final.empty:
        L += ["*No index cleared the filters.*", ""]
    else:
        if index_final["direction"].nunique() == 1 and len(index_final) > 1:
            L += ["> ⚠ All index picks point the same way — they move together, "
                  "so this is ONE bet sized as several. Consider taking only one.", ""]
        for _, r in index_final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L += [f"### {r['symbol']} — {struct}", "", _spread_line(r), f"- {r['reason']}", ""]
    for key, names in (index_excluded or {}).items():
        if names:
            L.append(f"- *{key}:* {', '.join(names)}")
    L += ["", "## NIFTY 50 stocks — information only, not traded (Stage 8n)", ""]

    L += [
        f"**{summary['selected']} of {summary['screened']} screened** — "
        f"{summary['up']} bull put / {summary['down']} bear call.",
        f"Sectors: {', '.join(summary['sectors']) or '—'}. "
        f"Mean beta {summary['mean_beta_up']} UP vs {summary['mean_beta_down']} DOWN.",
        f"Candidate supply after filters: {summary['supply_up']} UP / {summary['supply_down']} DOWN.",
        "",
    ]
    if summary["down"] < summary["up"]:
        L += ["> ⚠ Book is not balanced — not enough DOWN-side candidates survived "
              "the filters. Consider trading fewer positions rather than forcing "
              "in a weak bear call.", ""]

    if final.empty:
        L += ["*Nothing cleared the filters today. That is a valid outcome — "
              "sitting out is a position.*", ""]
    else:
        for _, r in final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L += [
                f"### {r['symbol']} — {struct}  ·  score {r['setup_score']}  ·  {r['sector']}",
                "",
                _spread_line(r),
                f"- {r['reason']}",
                "",
            ]

    L += ["---", "", "## Excluded (considered and rejected)", ""]
    labels = {
        "no_edge_either_side": "No edge either side — signal never worked on this stock",
        "wrong_side_watchlist": "Wrong side — other direction is the stronger one",
        "crash_born_flip": "Flip born on an outlier day — stats do not describe it",
        "thin_buffer_to_flip": "Too close to invalidating the trend",
        "trend_underwater": "Trend already running against its own entry",
        "weak_trend_adx": "Weak trend at the flip — ADX(14) not above 20",
        "sector_cap": "Sector already filled",
    }
    for key, label in labels.items():
        names = excluded.get(key) or []
        if names:
            L.append(f"- **{label}:** {', '.join(names)}")
    L += [
        "",
        "---",
        "",
        "## Still manual — not in this list",
        "",
        "- **Earnings / corporate actions** — no data source exists in Kite Connect.",
        "- **IV rank** — unbuilt; return on margin is shown, but nothing yet says whether",
        "  the premium is rich or cheap for this underlying.",
        "- **Options liquidity** — handled manually by choice.",
        "- **Exits** — deliberately not modelled. `exhaustion_test.py` found no usable",
        "  duration-based exit signal, and profit-target / DTE rules are untested here.",
        "",
        "*All statistics are in-sample and descriptive: computed on the same ~4 years",
        "the ranking is built from, with no walk-forward validation.*",
    ]
    return "\n".join(L)


def _compact_spread(r):
    if "lots" not in r or pd.isna(r.get("lots")):
        return f"  {'':11} {r.get('spread_problem') or 'spread not priced'}"
    opt = "PE" if r["direction"] == "UP" else "CE"
    flags = []
    if bool(r.get("lot_too_big", False)):
        flags.append("1 LOT OVER CAP")
    if bool(r.get("strike_inside_sl", False)):
        flags.append("strike inside SL")
    if _dte(r) <= 7:
        flags.append(f"{_dte(r)}d to expiry")
    return (f"  {'':11} {r['short_strike']:,.0f}/{r['long_strike']:,.0f} {opt} {r['expiry']}"
            f"  {r['strike_distance_pct']:.1f}% OTM  credit {r['credit']:.2f}"
            f"  {int(r['lots'])} lot  max loss ₹{r['max_loss_total']:,.0f}"
            f"  credit ₹{r['credit_total']:,.0f}  RoM {r['return_on_margin_pct']:.2f}%"
            + (f"  [{', '.join(flags)}]" if flags else ""))


def render_compact(final, excluded, summary, index_final=None, risk=None):
    """
    One-screen table for the terminal. The full markdown report still gets
    written either way — this exists because ~60 lines of markdown is exactly
    the length editors and terminals start collapsing, which buries the list.
    """
    L = [f"ENTRY LIST  {datetime.now():%Y-%m-%d %H:%M}", ""]
    if risk:
        L += [f"  BOOK: max loss ₹{risk['max_loss']:,} ({risk['max_loss_pct']}% of capital)"
              f"  credit ₹{risk['credit']:,}  margin ₹{risk['margin']:,} ({risk['margin_pct']}%)", ""]
    if risk and "vix" in risk:
        L += [f"  {VIX_LINE(risk)}" + ("  ** high: moves broke the implied range 2.4x as often (Stage 8j) **"
                                        if risk["vix_regime"] == "HIGH" else ""), ""]
    L.append("  INDICES")
    if index_final is None or index_final.empty:
        L.append("  none cleared the filters")
    else:
        if index_final["direction"].nunique() == 1 and len(index_final) > 1:
            L.append("  ** all same direction — one correlated bet, consider taking only one **")
        for _, r in index_final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L.append(f"  {r['symbol']:<11} {struct:<10} {int(r['trend_age_days']):>3}d  spot "
                     f"{r['spot']:,.1f}  SL {r['flip_level']:,.1f}  buffer {r['buffer_to_flip_pct']:.1f}%")
            L.append(_compact_spread(r))
    L += ["", f"  NIFTY 50 STOCKS (information only, not traded)   {summary['up']} bull put / {summary['down']} bear call"
              f"   beta {summary['mean_beta_up']} UP vs {summary['mean_beta_down']} DOWN", ""]
    if summary["down"] != summary["up"]:
        L += ["  ** NOT BALANCED — too few DOWN candidates survived; "
              "consider trading fewer positions **", ""]

    if final.empty:
        L += ["  nothing cleared the filters — sitting out is a position", ""]
    else:
        L.append(f"  {'SYMBOL':<11} {'STRUCTURE':<10} {'AGE':>4} {'STRIKE':>10}  "
                    f"{'SPOT':>10}  {'SECTOR':<11} {'WIN':>5} {'C6%':>6} {'BUF':>5} {'ADX':>5} {'SC':>5}")
        L.append("  " + "-" * 95)
        for _, r in final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L.append(f"  {r['symbol']:<11} {struct:<10} {int(r['trend_age_days']):>3}d {(r['short_strike'] if pd.notna(r.get('short_strike')) else r.get('suggested_strike')):>10,.1f}  "
                        f"{r['spot']:>10,.1f}  {r['sector']:<11} "
                        f"{r['dir_win_rate']:>4.1f}% {r['contained_6pct']:>5.1f}% "
                        f"{r['buffer_to_flip_pct']:>4.1f}% {r['adx_at_flip']:>5.1f} {r['setup_score']:>5.1f}")
            if "lots" in r:
                L.append(_compact_spread(r))
    L.append("")
    n_ex = sum(len(v or []) for v in excluded.values())
    L.append(f"  {n_ex} excluded — see the full report for names and reasons")
    L.append("  still manual: earnings, IV, liquidity, exits")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12, help="total positions (split 50/50)")
    ap.add_argument("--top", type=int, default=None,
                    help="limit to the top N NIFTY 50 stocks by ranking (default: all)")
    ap.add_argument("--no-refresh", action="store_true", help="skip the API catch-up")
    ap.add_argument("--full", action="store_true",
                    help="print the full markdown instead of the compact table")
    ap.add_argument("--max-per-sector", type=int, default=2,
                    help="cap per sector, applied PER DIRECTION (default 2)")
    args = ap.parse_args()

    from src.entry_advisor import build_entry_list, build_index_list, INDEX_UNIVERSE
    symbols = shortlist_symbols(args.top)
    errors = [] if args.no_refresh else refresh(symbols)

    stocks = [s for s in symbols if s not in INDEX_UNIVERSE]
    final, excluded, summary = build_entry_list(stocks, n_total=args.n,
                                                max_per_sector=args.max_per_sector)
    index_final, index_excluded = build_index_list()

    risk = None
    if not args.no_refresh:
        from src.auth import get_kite
        from src.spread_builder import add_spreads, risk_summary, vix_context
        kite = get_kite()
        index_final = add_spreads(kite, index_final, set(INDEX_UNIVERSE))
        final = add_spreads(kite, final, set(INDEX_UNIVERSE))
        risk = risk_summary(index_final)          # the traded book = indices
        try:
            risk.update(vix_context(kite))
        except Exception as e:
            risk["vix_error"] = str(e)

    out = render(final, excluded, summary, errors, index_final, index_excluded, risk)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    # Timestamped copy for history, plus a STABLE path so the file can be left
    # open in a markdown preview and simply refresh on each run instead of
    # having to be reopened by a new name twice a day.
    stamped = os.path.join(REPORTS_DIR, f"{datetime.now():%Y-%m-%d_%H%M}_entry_list.md")
    latest = os.path.join(REPORTS_DIR, "latest_entry_list.md")
    for p in (stamped, latest):
        with open(p, "w") as f:
            f.write(out)

    if errors:
        print(f"  ** {len(errors)} refresh problems — see full report **")
    print(out if args.full else render_compact(final, excluded, summary, index_final, risk))
    print(f"\n  full report: reports/latest_entry_list.md")

    # Paper journal: every name on this list is logged as a trade and tracked
    # to SL hit or expiry (src/credit_spread_journal.py). Skipped with
    # --no-refresh: exits must be judged on fresh candles, not saved ones.
    if not args.no_refresh:
        from src.auth import get_kite
        from src.credit_spread_journal import run_journal
        # Index trades only (TRADING_RULES.md / Stage 8n): stocks are shown for
        # information but are not part of the traded system.
        journal, logged, problems = run_journal(kite, index_final, already_refreshed=symbols)
        n_open = int((journal["status"] == "OPEN").sum())
        print(f"\n  journal: {len(logged)} new trade(s) logged"
              f"{' (' + ', '.join(logged) + ')' if logged else ''}, {n_open} open"
              f" — logs/credit_spread_journal.csv")
        for p in problems:
            print(f"  ** journal: {p}")


if __name__ == "__main__":
    main()
