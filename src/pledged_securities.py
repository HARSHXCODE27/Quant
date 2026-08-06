# src/pledged_securities.py
#
# NEW small module (this new sub-project) — loads the finalized pledgeable
# shares+ETFs universe from data/processed/Zerodha_Approved_Securities_Cleaned.xlsx
# ("Shares" and "ETFs" sheets, user-curated: haircut<=11, one pick per ETF
# theme). Kept separate from instruments.py since that file's job is F&O
# instrument/token lookups for the *existing* 218-stock+8-index universe;
# this one's job is the *pledgeable-securities* universe, which only
# partially overlaps with F&O (many pledgeable shares aren't F&O-enabled,
# and no ETF has its own listed F&O contract at all — see docstring below).

import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")
SECURITIES_FILE = os.path.join(PROJECT_ROOT, "data", "processed",
                                "Zerodha_Approved_Securities_Cleaned.xlsx")


def load_pledged_universe(fno_symbol_list=None):
    """
    Returns one DataFrame combining the "Shares" and "ETFs" sheets:
    symbol, security_name, security_type (Equity/ETF), etf_category
    (blank for shares), haircut_value, directly_fno_tradable.

    directly_fno_tradable matters because a Supertrend flip on these two
    groups means very different things in practice:
      - Equity rows that ARE F&O-enabled: flip = same directional
        credit-spread entry logic already built for the 4H universe, just
        timed off 1D instead.
      - ETF rows (and non-F&O-enabled Equity rows): NSE doesn't list
        options/futures on individual ETFs or on most of these shares —
        a flip here has no direct F&O contract to act on. For the 5
        broad-index ETF categories (Nifty 50/Next 50/100, Bank Nifty,
        Sensex) the flip should really be read off the INDEX itself
        (already in the existing 8-index universe), not the ETF — the
        ETF's only role is being the thing that's actually pledged. For
        Gold/Silver, the flip is a proxy signal for MCX commodity F&O
        (same pattern as the user's existing GOLDCASE approach). For
        everything else (sector/factor ETFs, non-F&O shares), a flip is
        informational only — there's no F&O instrument to trade against it.

    fno_symbol_list: pass the live F&O universe (e.g.
    get_fno_stock_list(kite) + the 8 index symbols) to flag accurately.
    If omitted, falls back to checking which symbols already have an
    exports/{symbol}_full_report.xlsx from the existing 4H pipeline — a
    reasonable proxy, but NOT authoritative if the F&O list has since
    changed (stocks get added/removed from F&O periodically).
    """
    if not os.path.exists(SECURITIES_FILE):
        raise FileNotFoundError(
            f"{SECURITIES_FILE} not found — run/save the cleaned securities "
            "workbook first (see data/processed/)."
        )

    shares = pd.read_excel(SECURITIES_FILE, sheet_name="Shares")
    shares["etf_category"] = ""
    etfs = pd.read_excel(SECURITIES_FILE, sheet_name="ETFs")

    cols = ["symbol", "security_name", "security_type", "etf_category", "haircut_value"]
    combined = pd.concat([shares[cols], etfs[cols]], ignore_index=True)

    if fno_symbol_list is not None:
        fno_set = set(fno_symbol_list)
    else:
        fno_set = set(
            f.replace("_full_report.xlsx", "")
            for f in os.listdir(EXPORTS_DIR)
            if f.endswith("_full_report.xlsx")
        )

    combined["directly_fno_tradable"] = combined["symbol"].isin(fno_set)
    return combined


def get_symbol_list():
    """Just the symbol column, as a plain list — convenience for pipeline calls."""
    return load_pledged_universe()["symbol"].tolist()
