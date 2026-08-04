# src/debit_spread_screener.py
#
# NEW live screener for the debit spread strategy (Stage 9), parallel to
# daily_screener.py - not a modification of it, and same separation of
# concerns: this reads whatever the LAST refresh already saved
# (exports/debit_spread/{symbol}_trades.csv) - it does NOT fetch data
# itself. Refresh the shortlist first (reuse
# debit_spread_scale_pipeline.process_instrument - same "only refresh what
# you're about to trade, same session" discipline as the existing
# screener), then call this.
#
# daily_screener.py checks a stock's currently-open Supertrend TREND AGE;
# this checks for a currently-OPEN debit-spread TRADE - a signal that fired
# recently and hasn't yet resolved (stop/target/time-exit) - the actionable
# entry itself, with live stop/target levels and candles left before the
# time-exit forces a close.

import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "debit_spread")

def check_active_trade(symbol, time_exit_candles=14):
    """
    Reads {symbol}'s already-refreshed trades file and returns details of
    its currently-OPEN trade (if any) - most of the time this returns None,
    since the signal only fires ~1-2x/month per instrument. `time_exit_candles`
    must match whatever was passed to simulate_trades() during the refresh -
    it's used to compute how many candles remain before the position gets
    forced closed by the time-exit, not re-derived from the saved row.
    """
    path = os.path.join(EXPORTS_DIR, f"{symbol}_trades.csv")
    if not os.path.exists(path):
        print(f"No trades file found for {symbol} - refresh it first")
        return None

    trades = pd.read_csv(path)
    open_trades = trades[trades["status"] == "OPEN"]
    if open_trades.empty:
        return None
    trade = open_trades.iloc[-1]  # simulate_trades runs chronologically - last row is most recent

    candles_left = max(time_exit_candles - int(trade["candles_held"]), 0)

    return {
        "symbol": symbol,
        "direction": trade["direction"],
        "entry_date": trade["entry_date"],
        "entry_price": trade["entry_price"],
        "stop_price": trade["stop_price"],
        "target_price": trade["target_price"],
        "candles_held": int(trade["candles_held"]),
        "candles_left_before_time_exit": candles_left,
        "current_pct_move": trade["pct_move"],
        "current_r": trade["r_achieved"],
    }

def screen_shortlist(symbol_list, time_exit_candles=14):
    """
    symbol_list should be a short, already-refreshed shortlist (e.g. top N
    from RANKING_debit_spread.xlsx, refreshed this session) - same
    discipline as daily_screener.screen_list: never point this at the full
    universe, only at what you're actually about to consider trading.
    """
    results = [check_active_trade(s, time_exit_candles=time_exit_candles) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])
