# src/iv_recorder.py
#
# Daily IV snapshot recorder — the forward-collection half of the IV rank gap
# (README's "main gap": nothing here says whether a premium is worth taking,
# and it can't be backfilled because expired option contracts roll off Kite's
# instrument dump, so no historical IV series exists to mine). The only path
# is to start recording now and let a usable percentile build up over time
# (see market_context.realized_vol_rank for the backfillable interim proxy
# used in the meantime).
#
# For each symbol: finds the nearest expiry with at least MIN_DTE days left,
# the strike nearest live spot, fetches that CE and PE's last_price, and
# backs out IV via Black-Scholes (src/black_scholes.py — Kite gives no IV
# field directly). Appends one row per symbol per day to
# logs/iv_history/{symbol}.csv — tracked in git (unlike exports/ and data/),
# because unlike everything else this project regenerates from Kite on
# demand, this series is genuinely irreplaceable if lost: today's snapshot
# can never be re-fetched once the day has passed.
#
# Run once a day, ideally near market close (same EOD-settle reasoning as
# scripts/refresh_token.py's 4H/1H siblings) via scripts/record_iv_snapshot.py.

import os
from datetime import date, datetime

import pandas as pd

from src.black_scholes import implied_vol
from src.instruments import INDEX_SYMBOLS

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(PROJECT_ROOT, "logs", "iv_history")

MIN_DTE = 7  # skip expiries closer than this - too little time value for a stable IV solve


def _spot_instrument(symbol):
    if symbol in INDEX_SYMBOLS:
        tradingsymbol, exchange = INDEX_SYMBOLS[symbol]
        return f"{exchange}:{tradingsymbol}"
    return f"NSE:{symbol}"


def _nearest_expiry(options, min_dte=MIN_DTE, today=None):
    today = today or date.today()
    expiries = sorted(options["expiry"].unique())
    for exp in expiries:
        exp_date = exp if isinstance(exp, date) else pd.Timestamp(exp).date()
        dte = (exp_date - today).days
        if dte >= min_dte:
            return exp, dte
    return None, None


def snapshot_symbol(symbol, instruments, kite, today=None):
    """
    Returns one row (dict) for `symbol`, or None if it has no NFO options
    (e.g. SENSEX - listed on BFO, not NFO - or no expiry far enough out) or
    the quote/IV solve fails. No fabricated fallback on any missing piece.
    """
    opts = instruments[(instruments["name"] == symbol) & (instruments["instrument_type"].isin(["CE", "PE"]))]
    if opts.empty:
        return None

    expiry, dte = _nearest_expiry(opts, today=today)
    if expiry is None:
        return None
    opts = opts[opts["expiry"] == expiry]

    spot_key = _spot_instrument(symbol)
    ltp = kite.ltp([spot_key])
    spot = ltp.get(spot_key, {}).get("last_price")
    if not spot:
        return None

    # Nearest strike that has BOTH a CE and a PE listed - the strike grid
    # isn't always symmetric (found via ULTRACEMCO: a CE existed one strike
    # closer to spot than any matching PE), so picking nearest-to-spot off
    # the union of strikes can land on one side only.
    ce_strikes = set(opts[opts["instrument_type"] == "CE"]["strike"])
    pe_strikes = set(opts[opts["instrument_type"] == "PE"]["strike"])
    common_strikes = ce_strikes & pe_strikes
    if not common_strikes:
        return None
    atm_strike = min(common_strikes, key=lambda k: abs(k - spot))

    ce_row = opts[(opts["strike"] == atm_strike) & (opts["instrument_type"] == "CE")]
    pe_row = opts[(opts["strike"] == atm_strike) & (opts["instrument_type"] == "PE")]
    if ce_row.empty or pe_row.empty:
        return None
    ce_ts, pe_ts = ce_row.iloc[0]["tradingsymbol"], pe_row.iloc[0]["tradingsymbol"]

    quotes = kite.quote([f"NFO:{ce_ts}", f"NFO:{pe_ts}"])
    ce_price = quotes.get(f"NFO:{ce_ts}", {}).get("last_price")
    pe_price = quotes.get(f"NFO:{pe_ts}", {}).get("last_price")
    if not ce_price or not pe_price:
        return None

    T = dte / 365
    ce_iv = implied_vol(ce_price, spot, atm_strike, T, "CE")
    pe_iv = implied_vol(pe_price, spot, atm_strike, T, "PE")
    ivs = [v for v in (ce_iv, pe_iv) if v is not None]
    atm_iv = round(sum(ivs) / len(ivs), 4) if ivs else None

    return {
        "date": (today or date.today()).isoformat(),
        "symbol": symbol,
        "spot": round(float(spot), 2),
        "expiry": str(expiry),
        "dte": dte,
        "atm_strike": atm_strike,
        "ce_price": ce_price,
        "pe_price": pe_price,
        "ce_iv": ce_iv,
        "pe_iv": pe_iv,
        "atm_iv": atm_iv,
    }


def append_snapshot(row):
    """
    One row per symbol per day - a re-run on the same day REPLACES that
    day's row (keep="last") rather than duplicating it, so this stays safe
    to re-run.
    """
    os.makedirs(HISTORY_DIR, exist_ok=True)
    path = os.path.join(HISTORY_DIR, f"{row['symbol']}.csv")

    new_row = pd.DataFrame([row])
    if os.path.exists(path):
        existing = pd.read_csv(path)
        combined = pd.concat([existing, new_row], ignore_index=True)
        combined = combined.drop_duplicates(subset="date", keep="last").sort_values("date")
    else:
        combined = new_row

    combined.to_csv(path, index=False)
    return path


def record_all(symbols, kite):
    """
    Fetches the NFO instrument dump ONCE and reuses it across all symbols -
    the expensive part is per-symbol quote() calls, not the dump itself.
    Isolated per-symbol failure handling, same discipline as every other
    scale pipeline in this project - one bad symbol never aborts the run.
    """
    instruments = pd.DataFrame(kite.instruments("NFO"))
    today = date.today()

    recorded, skipped = [], []
    for i, symbol in enumerate(symbols, start=1):
        try:
            row = snapshot_symbol(symbol, instruments, kite, today=today)
            if row is None:
                print(f"[{i}/{len(symbols)}] {symbol} — no valid option/quote, skipped")
                skipped.append(symbol)
                continue
            append_snapshot(row)
            print(f"[{i}/{len(symbols)}] {symbol} — ATM IV {row['atm_iv']} "
                  f"(strike {row['atm_strike']}, {row['dte']}d to expiry)")
            recorded.append(symbol)
        except Exception as e:
            print(f"[{i}/{len(symbols)}] {symbol} — FAILED: {e}")
            skipped.append(symbol)

    print(f"\n{len(recorded)} recorded, {len(skipped)} skipped/failed, {datetime.now().isoformat(timespec='seconds')}")
    return recorded, skipped
