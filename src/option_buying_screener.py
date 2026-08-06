# src/option_buying_screener.py
#
# NEW live screener for the naked-option-buying strategy, parallel to
# debit_spread_screener.py - same separation of concerns: reads whatever the
# last refresh already saved (exports/option_buying/{symbol}_trades.csv),
# does NOT fetch data itself. Refresh the shortlist first, same discipline
# as the debit spread screener, then call this.

import os
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "exports", "option_buying")

def check_active_trade(symbol, time_exit_candles=14):
    """
    Reads {symbol}'s already-refreshed trades file and returns details of
    its currently-OPEN trade (if any). time_exit_candles must match whatever
    was passed to simulate_trades() during the refresh - used to compute
    candles remaining before the time-exit forces a close.
    """
    path = os.path.join(EXPORTS_DIR, f"{symbol}_trades.csv")
    if not os.path.exists(path):
        print(f"No trades file found for {symbol} - refresh it first")
        return None

    trades = pd.read_csv(path)
    open_trades = trades[trades["status"] == "OPEN"]
    if open_trades.empty:
        return None
    trade = open_trades.iloc[-1]

    candles_left = max(time_exit_candles - int(trade["candles_held"]), 0)

    return {
        "symbol": symbol,
        "direction": trade["direction"],
        "entry_date": trade["entry_date"],
        "entry_price": trade["entry_price"],
        "initial_stop_price": trade["initial_stop_price"],
        "current_stop_price": trade["final_stop_price"],
        "trailing_activated": trade["trailing_activated"],
        "candles_held": int(trade["candles_held"]),
        "candles_left_before_time_exit": candles_left,
        "current_pct_move": trade["pct_move"],
        "current_r": trade["r_achieved"],
    }

def screen_shortlist(symbol_list, time_exit_candles=14):
    """Same shortlist discipline as debit_spread_screener.screen_shortlist -
    only point this at an already-refreshed shortlist, never the full universe."""
    results = [check_active_trade(s, time_exit_candles=time_exit_candles) for s in symbol_list]
    return pd.DataFrame([r for r in results if r is not None])
