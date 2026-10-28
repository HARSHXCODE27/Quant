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
RANKING = os.path.join(PROJECT_ROOT, "exports", "RANKING_credit_spreads.xlsx")


def shortlist_symbols(top_n=50):
    ranking = pd.read_excel(RANKING)
    clean = ranking[ranking["gap_risk_flag"].isna() | (ranking["gap_risk_flag"] == "")]
    syms = clean.head(top_n)["symbol"].tolist() + ["NIFTY", "BANKNIFTY"]
    return list(dict.fromkeys(syms))


def refresh(symbols):
    """Incremental candle catch-up for the shortlist only. The one API step."""
    from src.auth import get_kite
    from src.instruments import build_nse_token_lookup, get_index_token
    from src.scale_pipeline import process_stock_incremental

    kite = get_kite()
    lookup = build_nse_token_lookup(kite)
    index_symbols = {"NIFTY": ("NIFTY 50", "NSE"), "BANKNIFTY": ("NIFTY BANK", "NSE")}

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


def render(final, excluded, summary, refresh_errors):
    now = datetime.now()
    L = [f"# Entry list — {now:%Y-%m-%d %H:%M}", ""]

    if refresh_errors:
        L += ["## ⚠ Refresh problems", ""] + [f"- {e}" for e in refresh_errors] + [""]

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

    L += ["---", "", "## The list", ""]
    if final.empty:
        L += ["*Nothing cleared the filters today. That is a valid outcome — "
              "sitting out is a position.*", ""]
    else:
        for _, r in final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L += [
                f"### {r['symbol']} — {struct}  ·  score {r['setup_score']}  ·  {r['sector']}",
                "",
                f"- **Short strike ~{r['short_strike']}** "
                f"({r['strike_buffer_pct']}% from spot {r['spot']})",
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
        "- **IV rank** — unbuilt; nothing here says whether the premium is worth taking.",
        "- **Options liquidity** — handled manually by choice.",
        "- **Exits** — deliberately not modelled. `exhaustion_test.py` found no usable",
        "  duration-based exit signal, and profit-target / DTE rules are untested here.",
        "",
        "*All statistics are in-sample and descriptive: computed on the same ~4 years",
        "the ranking is built from, with no walk-forward validation.*",
    ]
    return "\n".join(L)


def render_compact(final, excluded, summary):
    """
    One-screen table for the terminal. The full markdown report still gets
    written either way — this exists because ~60 lines of markdown is exactly
    the length editors and terminals start collapsing, which buries the list.
    """
    L = [
        f"ENTRY LIST  {datetime.now():%Y-%m-%d %H:%M}   "
        f"{summary['up']} bull put / {summary['down']} bear call"
        f"   beta {summary['mean_beta_up']} UP vs {summary['mean_beta_down']} DOWN",
        "",
    ]
    if summary["down"] != summary["up"]:
        L += ["  ** NOT BALANCED — too few DOWN candidates survived; "
              "consider trading fewer positions **", ""]

    if final.empty:
        L += ["  nothing cleared the filters — sitting out is a position", ""]
    else:
        L.append(f"  {'SYMBOL':<11} {'STRUCTURE':<10} {'AGE':>4} {'STRIKE':>10}  "
                    f"{'SPOT':>10}  {'SECTOR':<11} {'WIN':>5} {'C6%':>6} {'BUF':>5} {'SC':>5}")
        L.append("  " + "-" * 89)
        for _, r in final.iterrows():
            struct = "BULL PUT" if r["direction"] == "UP" else "BEAR CALL"
            L.append(f"  {r['symbol']:<11} {struct:<10} {int(r['trend_age_days']):>3}d {r['short_strike']:>10,.1f}  "
                        f"{r['spot']:>10,.1f}  {r['sector']:<11} "
                        f"{r['dir_win_rate']:>4.1f}% {r['contained_6pct']:>5.1f}% "
                        f"{r['buffer_to_flip_pct']:>4.1f}% {r['setup_score']:>5.1f}")
    L.append("")
    n_ex = sum(len(v or []) for v in excluded.values())
    L.append(f"  {n_ex} excluded — see the full report for names and reasons")
    L.append("  still manual: earnings, IV, liquidity, exits")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12, help="total positions (split 50/50)")
    ap.add_argument("--top", type=int, default=50, help="how deep into the ranking to screen")
    ap.add_argument("--no-refresh", action="store_true", help="skip the API catch-up")
    ap.add_argument("--full", action="store_true",
                    help="print the full markdown instead of the compact table")
    ap.add_argument("--max-per-sector", type=int, default=2,
                    help="cap per sector, applied PER DIRECTION (default 2)")
    args = ap.parse_args()

    symbols = shortlist_symbols(args.top)
    errors = [] if args.no_refresh else refresh(symbols)

    from src.entry_advisor import build_entry_list
    final, excluded, summary = build_entry_list(symbols, n_total=args.n,
                                                max_per_sector=args.max_per_sector)

    out = render(final, excluded, summary, errors)
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
    print(out if args.full else render_compact(final, excluded, summary))
    print(f"\n  full report: reports/latest_entry_list.md")

    # Paper journal: every name on this list is logged as a trade and tracked
    # to SL hit or expiry (src/credit_spread_journal.py). Skipped with
    # --no-refresh: exits must be judged on fresh candles, not saved ones.
    if not args.no_refresh:
        from src.auth import get_kite
        from src.credit_spread_journal import run_journal
        journal, logged, problems = run_journal(get_kite(), final, already_refreshed=symbols)
        n_open = int((journal["status"] == "OPEN").sum())
        print(f"\n  journal: {len(logged)} new trade(s) logged"
              f"{' (' + ', '.join(logged) + ')' if logged else ''}, {n_open} open"
              f" — logs/credit_spread_journal.csv")
        for p in problems:
            print(f"  ** journal: {p}")


if __name__ == "__main__":
    main()
