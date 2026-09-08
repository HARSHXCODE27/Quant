# src/market_context.py
#
# Live market context for the entry list — the three things the screener could
# not answer because daily_screener.py deliberately reads only exports/:
#
#   1. buffer_to_flip_pct  - how far spot sits from the Supertrend level that
#      would invalidate the open trend. A trend 0.3% from flipping is a
#      different proposition from one 5% away, and NOTHING in the screener
#      showed this. NIFTY sat at 0.27% on 2026-08-12 while topping the
#      containment table; BANKNIFTY was 1.26% and already underwater.
#   2. beta_vs_nifty       - so a directionally balanced book is actually
#      SHOCK balanced. Three bear calls on defensive FMCG names do not offset
#      three bull puts on the index; equal counts, very unequal crash response.
#   3. sector              - the concentration limit the README flags as a real
#      unbuilt gap (ICICIPRULI + HDFCBANK + BANKNIFTY once shared a top-15).
#   4. realized_vol_rank   - backfillable interim proxy for the IV rank gap
#      (see README's "main gap" and Stage 8f) - is this stock more or less
#      volatile than its OWN normal range right now. Not IV, but the closest
#      thing available from price history alone; see realized_vol_rank()'s
#      own docstring for the real forward-collected IV recorder.
#
# All of it comes from data already on disk. No API calls.

import os
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports")

BETA_LOOKBACK_DAYS = 250   # ~1 trading year
BETA_MIN_OBSERVATIONS = 60

REALIZED_VOL_WINDOW = 20        # ~1 trading month
REALIZED_VOL_LOOKBACK_DAYS = 500  # ~2 years, the percentile base
REALIZED_VOL_MIN_HISTORY = 120  # need a real distribution before a rank means anything

# Static sector map. Public classification, maintained by hand — a symbol not
# listed here comes back as "UNKNOWN" and is skipped by the concentration check
# rather than silently counted as a sector of its own. Add to it as the F&O
# universe changes; nothing breaks if it lags.
SECTOR_MAP = {
    # Index
    "NIFTY": "INDEX", "BANKNIFTY": "INDEX", "FINNIFTY": "INDEX",
    "MIDCPNIFTY": "INDEX", "NIFTYNXT50": "INDEX", "SENSEX": "INDEX",
    # Banks & financials
    "HDFCBANK": "BANK", "ICICIBANK": "BANK", "KOTAKBANK": "BANK", "AXISBANK": "BANK",
    "SBIN": "BANK", "INDUSINDBK": "BANK", "BANKBARODA": "BANK", "PNB": "BANK",
    "CANBK": "BANK", "FEDERALBNK": "BANK", "IDFCFIRSTB": "BANK", "AUBANK": "BANK",
    "YESBANK": "BANK", "BANDHANBNK": "BANK", "RBLBANK": "BANK",
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "SHRIRAMFIN": "NBFC",
    "CHOLAFIN": "NBFC", "MUTHOOTFIN": "NBFC", "LICHSGFIN": "NBFC", "PFC": "NBFC",
    "RECLTD": "NBFC", "IRFC": "NBFC", "SBICARD": "NBFC", "NAM-INDIA": "NBFC",
    "HDFCLIFE": "INSURANCE", "SBILIFE": "INSURANCE", "ICICIPRULI": "INSURANCE",
    "ICICIGI": "INSURANCE", "LICI": "INSURANCE", "POLICYBZR": "INSURANCE",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "MPHASIS": "IT", "PERSISTENT": "IT", "COFORGE": "IT",
    "TATAELXSI": "IT", "NAUKRI": "IT", "OFSS": "IT",
    # Pharma & healthcare
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA", "LUPIN": "PHARMA",
    "AUROPHARMA": "PHARMA", "TORNTPHARM": "PHARMA", "ALKEM": "PHARMA",
    "ZYDUSLIFE": "PHARMA", "DIVISLAB": "PHARMA", "BIOCON": "PHARMA",
    "GLENMARK": "PHARMA", "LAURUSLABS": "PHARMA", "MANKIND": "PHARMA",
    "APOLLOHOSP": "HEALTHCARE", "MAXHEALTH": "HEALTHCARE", "FORTIS": "HEALTHCARE",
    # FMCG & consumer
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "MARICO": "FMCG", "COLPAL": "FMCG", "GODREJCP": "FMCG",
    "TATACONSUM": "FMCG", "VBL": "FMCG", "UBL": "FMCG", "RADICO": "FMCG",
    "PGHH": "FMCG", "EMAMILTD": "FMCG",
    "TITAN": "CONSUMER", "TRENT": "CONSUMER", "DMART": "CONSUMER",
    "JUBLFOOD": "CONSUMER", "PAGEIND": "CONSUMER", "ABFRL": "CONSUMER",
    # Auto
    "MARUTI": "AUTO", "M&M": "AUTO", "TATAMOTORS": "AUTO", "BAJAJ-AUTO": "AUTO",
    "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO", "TVSMOTOR": "AUTO",
    "ASHOKLEY": "AUTO", "BALKRISIND": "AUTO", "MOTHERSON": "AUTO",
    "BOSCHLTD": "AUTO", "TIINDIA": "AUTO", "EXIDEIND": "AUTO", "MRF": "AUTO",
    # Metals & mining
    "TATASTEEL": "METALS", "JSWSTEEL": "METALS", "HINDALCO": "METALS",
    "VEDL": "METALS", "JINDALSTEL": "METALS", "SAIL": "METALS", "NMDC": "METALS",
    "NATIONALUM": "METALS", "HINDZINC": "METALS", "APLAPOLLO": "METALS",
    # Energy & utilities
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "IOC": "ENERGY", "BPCL": "ENERGY",
    "HINDPETRO": "ENERGY", "GAIL": "ENERGY", "OIL": "ENERGY", "PETRONET": "ENERGY",
    "NTPC": "UTILITIES", "POWERGRID": "UTILITIES", "TATAPOWER": "UTILITIES",
    "ADANIGREEN": "UTILITIES", "ADANIENSOL": "UTILITIES", "JSWENERGY": "UTILITIES",
    "NHPC": "UTILITIES", "SJVN": "UTILITIES", "TORNTPOWER": "UTILITIES",
    # Cement & construction
    "ULTRACEMCO": "CEMENT", "SHREECEM": "CEMENT", "GRASIM": "CEMENT",
    "AMBUJACEM": "CEMENT", "ACC": "CEMENT", "DALBHARAT": "CEMENT",
    "LT": "INFRA", "ADANIPORTS": "INFRA", "CONCOR": "INFRA", "GMRAIRPORT": "INFRA",
    "IRB": "INFRA", "NBCC": "INFRA", "RVNL": "INFRA",
    # Chemicals
    "PIIND": "CHEMICALS", "SRF": "CHEMICALS", "UPL": "CHEMICALS",
    "PIDILITIND": "CHEMICALS", "DEEPAKNTR": "CHEMICALS", "TATACHEM": "CHEMICALS",
    "AARTIIND": "CHEMICALS", "ATUL": "CHEMICALS", "NAVINFLUOR": "CHEMICALS",
    "SOLARINDS": "CHEMICALS", "COROMANDEL": "CHEMICALS", "CHAMBLFERT": "CHEMICALS",
    # Industrials & electricals
    "HAVELLS": "ELECTRICALS", "POLYCAB": "ELECTRICALS", "CGPOWER": "ELECTRICALS",
    "SIEMENS": "ELECTRICALS", "ABB": "ELECTRICALS", "BHEL": "ELECTRICALS",
    "THERMAX": "ELECTRICALS", "VOLTAS": "ELECTRICALS", "CROMPTON": "ELECTRICALS",
    "DIXON": "ELECTRICALS", "PGEL": "ELECTRICALS", "WAAREEENER": "ELECTRICALS",
    "ASTRAL": "INDUSTRIALS", "SUPREMEIND": "INDUSTRIALS", "CUMMINSIND": "INDUSTRIALS",
    "BEL": "DEFENCE", "HAL": "DEFENCE", "BDL": "DEFENCE", "MAZDOCK": "DEFENCE",
    # Telecom & media
    "BHARTIARTL": "TELECOM", "IDEA": "TELECOM", "INDUSTOWER": "TELECOM",
    "TATACOMM": "TELECOM", "ZEEL": "MEDIA",
    # Realty
    "DLF": "REALTY", "OBEROIRLTY": "REALTY", "GODREJPROP": "REALTY",
    "PRESTIGE": "REALTY", "LODHA": "REALTY", "PHOENIXLTD": "REALTY",
    # Exchanges / capital markets
    "BSE": "CAPMKTS", "MCX": "CAPMKTS", "ANGELONE": "CAPMKTS", "CDSL": "CAPMKTS",
    "HDFCAMC": "CAPMKTS", "KFINTECH": "CAPMKTS", "IEX": "CAPMKTS",
}


def _daily_closes(symbol):
    """Daily close series from the saved 4H candles. Returns None if missing."""
    path = os.path.join(RAW_DIR, f"{symbol}_4hour.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    if df.empty:
        return None
    df["date"] = df["date"].dt.tz_localize(None) if df["date"].dt.tz is not None else df["date"]
    return df.set_index("date")["close"].groupby(lambda d: d.normalize()).last()


def compute_beta(symbol, benchmark="NIFTY", lookback_days=BETA_LOOKBACK_DAYS):
    """
    Beta of daily returns vs NIFTY over the trailing window.

    Used to make the 50/50 direction split mean something in a shock: a bear
    call on a beta-0.4 FMCG name is nearly useless as an offset to a bull put
    on a beta-1.3 index position, even though the counts look balanced.

    Plain OLS slope (cov/var) on overlapping daily returns. Returns None if
    either series is missing or too short — never a fabricated default, since
    a wrong beta is worse than a visibly absent one.
    """
    s = _daily_closes(symbol)
    b = _daily_closes(benchmark)
    if s is None or b is None:
        return None

    rs = s.pct_change().dropna().tail(lookback_days)
    rb = b.pct_change().dropna().tail(lookback_days)
    joined = pd.concat([rs, rb], axis=1, join="inner").dropna()
    joined.columns = ["stock", "bench"]
    if len(joined) < BETA_MIN_OBSERVATIONS:
        return None

    var = joined["bench"].var()
    if var == 0 or pd.isna(var):
        return None
    return round(float(joined["stock"].cov(joined["bench"]) / var), 2)


def current_position_vs_flip(symbol):
    """
    Where spot sits relative to the open flip: distance to the Supertrend level
    that would invalidate it, and how far the trend has travelled since entry.

    buffer_to_flip_pct is the single most decision-relevant number missing from
    the screener. moved_since_entry_pct is signed FOR the position: positive
    means the trend is working, negative means it is underwater.
    """
    report = os.path.join(EXPORTS_DIR, f"{symbol}_full_report.xlsx")
    if not os.path.exists(report):
        return {}
    flips = pd.read_excel(report, sheet_name="Flips")
    open_rows = flips[flips["status"] == "OPEN"]
    closes = _daily_closes(symbol)
    if open_rows.empty or closes is None or closes.empty:
        return {}

    op = open_rows.iloc[0]
    spot = float(closes.iloc[-1])
    st = float(op["final_sl_at_breach"])
    entry = float(op["entry_price"])
    sign = 1 if op["direction"] == "UP" else -1

    return {
        "spot": round(spot, 2),
        "flip_level": round(st, 2),
        "buffer_to_flip_pct": round(abs(spot - st) / spot * 100, 2),
        "moved_since_entry_pct": round((spot - entry) / entry * 100 * sign, 2),
    }


def realized_vol_rank(symbol, window=REALIZED_VOL_WINDOW, lookback_days=REALIZED_VOL_LOOKBACK_DAYS):
    """
    Backfillable interim proxy for the IV rank gap (README's "main gap" - no
    options pricing data exists here to compute a real IV rank; see
    src/iv_recorder.py for the forward-collection half of that). Realized
    vol is backward-looking, not the market's forward price of risk, but it
    answers a related practical question nothing else in this project asks:
    is this stock more or less volatile than its OWN normal range right now
    - relevant to whether a strike distance that looked safe over the 4yr
    containment history still is.

    `window`-day annualized realized volatility (stdev of daily log returns
    x sqrt(252)), then a percentile rank of TODAY's value against this
    stock's own trailing `lookback_days` history of that same rolling
    series. Returns None if there isn't enough daily-close history for a
    real distribution to rank against - never a rank computed off a handful
    of points.
    """
    closes = _daily_closes(symbol)
    if closes is None or len(closes) < REALIZED_VOL_MIN_HISTORY:
        return None

    log_returns = np.log(closes / closes.shift(1)).dropna()
    rolling_vol = (log_returns.rolling(window).std() * np.sqrt(252) * 100).dropna()
    history = rolling_vol.tail(lookback_days)
    if len(history) < REALIZED_VOL_MIN_HISTORY:
        return None

    current = float(history.iloc[-1])
    rank = float((history <= current).mean() * 100)
    return {"realized_vol_pct": round(current, 1), "realized_vol_rank": round(rank, 1)}


def get_sector(symbol):
    return SECTOR_MAP.get(symbol, "UNKNOWN")


def enrich(status):
    """
    Adds spot, flip_level, buffer_to_flip_pct, moved_since_entry_pct, beta,
    sector, and realized_vol_pct/realized_vol_rank to a screen_list() frame.
    Missing values stay None rather than being imputed — an absent number is
    visible, a guessed one is not.
    """
    df = status.copy()
    rows = []
    for symbol in df["symbol"]:
        ctx = current_position_vs_flip(symbol)
        ctx["symbol"] = symbol
        ctx["beta"] = compute_beta(symbol)
        ctx["sector"] = get_sector(symbol)
        vol = realized_vol_rank(symbol)
        ctx["realized_vol_pct"] = vol["realized_vol_pct"] if vol else None
        ctx["realized_vol_rank"] = vol["realized_vol_rank"] if vol else None
        rows.append(ctx)
    ctx_df = pd.DataFrame(rows)
    return df.merge(ctx_df, on="symbol", how="left")
