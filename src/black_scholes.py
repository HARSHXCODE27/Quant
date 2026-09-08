# src/black_scholes.py
#
# Plain Black-Scholes pricer + implied-vol solver. Needed because Kite Connect
# does not return option IV directly - only last_price - so IV has to be
# backed out from the traded price the same way every options desk does it.
# No dividend yield term: none of the underlyings this project trades pay a
# dividend large enough over a ~1-month option life to matter, and Kite has
# no forward-looking dividend data to plug in anyway - same "don't model what
# isn't measurable" standard as everywhere else here.

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

RISK_FREE_RATE = 0.065  # static approximation (~India short-term rate). IV is
                         # not very sensitive to r for short-dated options, so
                         # this being off by 50-100bps barely moves the result.


def bs_price(S, K, T, r, sigma, option_type):
    """Black-Scholes price. T in years, sigma annualized. option_type 'CE' or 'PE'."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(S - K, 0) if option_type == "CE" else max(K - S, 0)
        return intrinsic

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "CE":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_vol(market_price, S, K, T, option_type, r=RISK_FREE_RATE):
    """
    Solves for sigma via brentq on bs_price(sigma) - market_price = 0.
    Returns None if the price is below intrinsic value (arbitrage/stale quote,
    no valid IV exists) or brentq fails to bracket a root - never a guessed
    fallback value.
    """
    intrinsic = max(S - K, 0) if option_type == "CE" else max(K - S, 0)
    if market_price <= intrinsic or T <= 0:
        return None

    def f(sigma):
        return bs_price(S, K, T, r, sigma, option_type) - market_price

    try:
        # 0.001-5.0 = 0.1%-500% annualized vol, comfortably wider than any
        # real NSE F&O quote should ever land.
        return round(float(brentq(f, 0.001, 5.0)), 4)
    except ValueError:
        return None
