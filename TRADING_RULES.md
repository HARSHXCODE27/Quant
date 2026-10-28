# Trading rules — the current best system

*Last updated 2026-10-29. The README stages linked below hold the full evidence.
Change this file only when a test beats an entry in the scoreboard. Add the new
result to "What was tested".*

## The system (what to do)

| | Rule |
|---|---|
| **Instruments** | **NIFTY, BANKNIFTY.** Gold is the next candidate (paper only, see "Pending"). NIFTY 50 stocks are shown on the list for information, not traded. |
| **Signal** | **4H Supertrend (10, 3)** on the index. A trend flip UP → **bull put spread**; a flip DOWN → **bear call spread**. |
| **When to check** | 13:20 and 15:35 IST, after each 4H candle closes (`scripts/daily_list.py` or notebook 06). |
| **Entry filters** | Skip if the flip was born on a > 4% day, if spot is < 1.5% from the Supertrend level, or if the trend is already > 1% against its own entry. |
| **Strike** | **First listed strike at or beyond 3% from spot.** |
| **Hedge** | Skip one strike, buy the next (index strikes in 100s → hedge 200 pts beyond). |
| **Expiry** | Current month's monthly expiry. |
| **Size** | Max loss per trade **1-2% of capital** (₹10-20k on ₹10L). Use 1% when VIX is high or the setup is weak. Total open max loss ≤ ~8%. NIFTY + BANKNIFTY in the same direction = **one bet**. |
| **Exit** | **Only two exits:** a 4H candle **closes** beyond the Supertrend level (stop), or expiry. No profit-taking, no adjustments. |
| **Orders** | Buy the hedge first, then sell. Limit orders near the mid. Let winners expire, don't buy them back. |
| **Capital** | Margin from pledged liquid ETF. Keep ~₹50-75k cash for hedge premiums, charges and losses (losses are debited from cash). |

**Win / loss rule (user's):** a trade **wins** if it reaches expiry with no flip
back, or if the stop exits beyond entry. It **loses** if the trend flips back first
and the exit is worse than entry. The strike plays no part.

## Scoreboard — what was tested and what won

| Question | Winner | Beaten / rejected | Stage |
|---|---|---|---|
| Timeframe | **4H** | 1H (worse on 100% of instruments), 2H (86%), 1D (wins more, loses bigger), intraday 5m/15m (nothing survives costs) | 8g, 8h |
| Indicator | **Supertrend 10,3** | ST 10,2 / 10,4 / 7,3 / 14,3, EMA 9/21 & 20/50, MACD, PSAR, DMI, Donchian, EMA200 filter | 8g |
| ADX filter | ADX > 20 helps **stocks only** | "ADX rising", "DI agrees" (failed holdout); on indices ADX raised strike hits | 8g, 8i |
| Instrument | **Indices (NIFTY, BANKNIFTY)**; gold equal to NIFTY and a diversifier | NIFTY 50 stocks (losses 2× bigger, book lost money at realistic premiums), other F&O stocks, SENSEX (negative in model) | 8i, 8l, 8n, 8p |
| Diversify into stocks? | **No: index only.** Same ₹10L book, same rules, 2022-26: **index only +₹68,310, worst drawdown −₹34,187, losing months 34%** vs **index + NIFTY 50 stocks −₹2,28,258, drawdown −₹2,81,117, losing months 69%** (at live-calibrated stock premiums; stocks only win if their options were ~25% richer than the model, and live quotes say ~19% cheaper). Without option prices: stocks win ~2.5 pts more often but each loss is **2.1× bigger** (−3.7% vs −1.7%), and losses over 3% are **5× as common** (29% vs 5% of trades), every year | Mixing stocks into the index book | 8n |
| Structure | **Directional credit spread** | 7% iron condor (earns ~0 after skew), VIX/ADX regime switch, plain monthly put spread (half the profit, 2× the drawdown) | 8m, 8q |
| Strike | **~3%** | 2% (bigger losses), 4-5% (costs eat the credit), "1.5% return on margin" (landed ~5%) | 8l |
| Exit | **Hold to the flip or expiry** | Profit-take at 25 / 50 / 75%; stop order at the line (untested, see Pending) | 8q |
| Entry timing | **Trade every qualifying flip** | Per-symbol "edge" filter (did not persist walk-forward), VIX regime (high VIX was worse, shown only), trend age | 8o, 8j, 6 |

## How good is it (honest)

- Profit is **thin**. In the model the NIFTY system makes about **₹4,600 / lot / year
  before slippage, ~₹1,900 after** (2015-26, Stage 8q). The ₹10L index book made
  +₹68k in 2022-26, almost all in 2022 (Stage 8n).
- It wins by **cutting losses** (avg loss ~₹1,400 / lot vs ~₹9,000 for selling
  without a stop), not by winning more often. Win rate is ~50%.
- **All rupee figures are modelled** (Black-Scholes at India VIX, no skew). Kite keeps
  no historical option prices. The paper journal (`logs/credit_spread_journal.csv`)
  is the real test. Review after 1-2 months before trading real money.

## Pending (not yet tested)

- **Gold:** MCX option premiums, MCX-session 4H flips vs GOLDBEES flips, real MCX expiry
  dates, GOLDBEES rebuilt from 5-minute data (needs a live token). Then a paper-only line.
- **Stop order at the Supertrend line** vs waiting for the 4H close (needs 5-min data
  to include the touch-and-revert stops).
- Weekly expiries, expiry-day selling, calendars: need historical option prices (not available).
