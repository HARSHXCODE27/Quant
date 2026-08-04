## Setup
1. Activate venv: `source .venv/bin/activate`
2. Install deps: `pip install kiteconnect pandas pandas_ta jupyter openpyxl`
3. Add API key/secret to `config/credentials.py` (gitignored — do not commit)
4. `git init` + confirm `.gitignore` excludes `config/credentials.py`, `config/access_token.txt`, `data/`, `.venv/`, `**/.DS_Store`

## Progress — Stages

### Stage 1 — Project scaffolding ✅
- [x] Folder structure, venv, Kite credentials
- [x] git initialized + `.gitignore` in place

### Stage 2 — Data pipeline (single stock) ✅
- [x] `auth.py`, `fetch_data.py` — built and tested on BHARTIARTL

### Stage 3 — Supertrend + flip detection ✅
- [x] `supertrend.py` applied, visually verified against Kite chart
- [x] `flip_analysis.py` — direction, duration, entry/exit, status (OPEN/CLOSED)
- [x] Enhanced: `max_adverse_pct` (worst move against position mid-trend, not just at exit),
      `gap_pct`/`max_gap_against_pct` (overnight/weekend jump risk)

### Stage 4 — Monthly range + summary automation ✅
- [x] `monthly_range.py` — range_pct, net_move_pct, up_move_pct, down_move_pct
- [x] Percentile columns added: 75th/90th for monthly range, up/down move, AND duration
- [x] `summary_stats.py` — fully automated version of the manual histogram analysis
      (totals, avg/median/min/max, monthly-cycle completion %, tail-risk counts)
- [x] `export_report.py` — single `{symbol}_full_report.xlsx` per stock, 3 sheets
      (Flips / Monthly Range / Summary)

### Stage 5 — Scale to all F&O stocks + indices ✅
- [x] `instruments.py` — F&O stock list (excludes index names to avoid duplicates),
      NSE token lookup, separate index token lookup (NIFTY, BANKNIFTY, SENSEX,
      FINNIFTY, MIDCPNIFTY, NIFTYNXT50 — SENSEX is BSE, not NSE)
- [x] `scale_pipeline.py` — resume support, isolated failure handling, rate-limit delays
- [x] 210 stocks + 8 indices fully processed and validated (210/215 stocks succeeded first
      run; 5 "failures" were index futures incorrectly appearing in the stock list, not
      real failures — indices processed separately)
- [x] `reprocess_all()` — recompute-only refresh (no API calls) for backfilling new metrics
      across all reports without re-fetching

### Stage 6 — Cross-stock comparison & strategy scoring ✅
- [x] `compare_stocks.py` — `ALL_STOCKS_COMPARISON.xlsx`, one row per stock, all metrics as columns
- [x] `strategy_scoring.py` — scoring functions, each a weighted percentile blend
      of metrics chosen specifically for that strategy's actual risk profile:
  - **`score_for_credit_spreads`** — favors trend persistence & low adverse movement.
    High priority: median max_adverse_pct, % completed within 30 days, median duration.
    Medium: worst max_adverse_pct, worst gap. Filter: ≥30 flips. Flags (doesn't exclude)
    stocks with worst gap >5%.
  - **`score_for_short_iron_condor`** — favors range containment, quick-reverting trends.
    High priority: median monthly range, median adverse, worst monthly range (all lower =
    better). Duration weighting flipped vs credit spreads (shorter = better). Stricter gap
    flag threshold (>4%).
  - ~~`score_for_long_iron_condor`~~ and ~~`score_for_directional_buying`~~ — **removed**
    (not needed going forward). Long IC had found a real, unresolved liquidity limitation
    (top-ranked names were mostly small/mid-cap with poor OTM options liquidity —
    historically volatile ≠ tradeable) before it was dropped. Their notebooks
    (`13_score_long_ic.ipynb`, `14_score_directional_buy.ipynb`), functions, and stale
    ranking exports were deleted together — verified nothing else referenced them
    (credit spreads, short IC, and debit spread all read different ranking files and
    share only `_pct_rank`/`_add_trend_age_flag`/`_add_volatility_persistence_flag`/
    `save_ranking`, none of which were touched).

### Stage 7 — Live decision support (built, NOT full automation) ✅
- [x] `daily_screener.py` — checks a stock's currently-OPEN trend age against its own
      historical median/75th percentile duration
- [x] `reversion_test.py` — tested whether aged trends predict reversal (see finding below)
- [x] Manual workflow established: pull top-N from a ranking → filter high-gap-risk →
      always include NIFTY/BANKNIFTY → refresh ONLY that shortlist with fresh API data →
      screen → apply human checklist (results dates, sector news, IV, concentration)
- [x] Full live/automated alert system (WebSocket, Telegram, always-on VPS) was scoped and
      deliberately **deferred** — advisory-only manual system judged sufficient until the
      strategy is proven with real trading experience

### Stage 8 — Live tracking / automation (future, not started)
- [ ] Only revisit if manual checking becomes a proven, felt bottleneck after real trading

### Stage 9 — Debit spread signal (EMA/ADX, 1H) — in progress
- [x] `src/ema_adx_signal.py` — NEW module, parallel to `flip_analysis.py` not a
      modification of it. EMA(9/21) crossover + rising-ADX confirmation, built for
      1H (Kite `60minute`) since 4H Supertrend lag directly costs premium/time decay
      on a debit spread (unlike premium-selling, where lag is fine).
- [x] Validated signal generation on one stock (BHARTIARTL, 1H, Jan 2025-Jul 2026,
      2738 candles) before scaling — same pattern as Stage 2 (single-stock build)
      before Stage 5 (scale to 218 stocks).
- [x] **Found and fixed a calibration bug during validation:** the first version
      required ADX to be "rising" on the *exact* crossover candle. This produced a
      6-month dead zone (Feb-Jul 2026) with zero confirmed signals despite 43 raw
      crossovers and ADX regularly running 20-45 in that window — ADX typically
      peaks just before/after the EMA cross, not exactly on it. Fixed with a
      `confirm_window` (default 2 candles after the cross, signal fires on the
      first candle ADX confirms — no lookahead, real-time safe). Kept 31/122 raw
      crossovers (25.4%) vs 14/122 (11.5%, too strict) for exact-candle and 76/122
      (62%, too loose) for no rising-check at all; 9 of the 31 land inside the
      previously-dead window.
- [x] `src/debit_spread_trades.py` — NEW trade-lifecycle module, parallel to
      `flip_analysis.py` not a modification of it. Exits are explicit instead of
      "hold until opposite signal": ATR(14)-based stop (1.5x ATR at entry),
      target = 1.5x the stop distance (R-multiple), and a 14-candle time exit if
      neither is hit (theta-decay guard — a stagnant debit spread bleeds premium,
      unlike a stagnant Supertrend hold). No overlapping trades — a new signal is
      ignored while an earlier trade is still open. STOP wins ties if one candle
      touches both levels (conservative, same worst-case framing as
      `max_adverse_pct`/`max_gap_against_pct` in flip_analysis.py).
- [x] First-pass validation on BHARTIARTL (1H, same 31 signals as above): 28
      trades (3 absorbed by the no-overlap rule), 50% win rate, avg 0.11R /
      median -0.45R, exits split STOP 14 / TARGET 10 / TIME 4, median 6.5
      candles held. **Reads as roughly breakeven, not a proven edge** — and
      28 trades on one stock is a small sample (well under the ≥30-flip /
      ≥15-flip minimums used elsewhere in this project before trusting a
      number). Not a green light to scale yet.
- [x] Validated on 2 more instruments — RELIANCE (large-cap, different sector)
      and NIFTY (index): RELIANCE 55.2% win rate / avg 0.30R (STOP 12 / TARGET
      14 / TIME 3); NIFTY 51.9% / avg 0.31R (STOP 11 / TARGET 13 / TIME 3).
      Both beat BHARTIARTL's near-breakeven read, and both hit TARGET more
      than STOP (unlike BHARTIARTL) — with the 1:1.5 stop:target payoff, that
      alone accounts for the positive average. Encouraging, but still only
      27-29 trades per instrument (below this project's own ≥30-flip bar) and
      only 3 instruments total, not a random sample of the universe. Also
      found and fixed the same **indicator warm-up issue** discovered here:
      the first ~3-4 weeks of any fetch produce unreliable EMA/ADX values —
      fixed by fetching from ~6 weeks before the intended analysis start
      (2024-11-15 vs the "real" 2025-01-01 start), not by manually trimming.
- [x] `src/debit_spread_scale_pipeline.py` — NEW batch runner, parallel to
      `scale_pipeline.py` + `compare_stocks.py`, not a modification of either.
      Runs signal + trade-lifecycle across all 218 stocks + 8 indices on 1H
      data, same resume/failure-isolation/rate-limit discipline as the
      original scale pipeline. Built so the full-universe win-rate/avg-R
      *distribution* — not 3 hand-picked stocks — is what decides whether
      this strategy's signal quality actually holds up.
- [x] **Ran the full-universe batch (214 instruments, Nov 2024-Aug 2026, ≥15
      closed trades each):** 59.3% showed a positive avg_r_achieved. Mean avg R
      0.077, median 0.06 — both positive but modest. Mean win rate 45.4%
      (below 50%, but above the ~40% breakeven rate for a 1:1.5 stop:target,
      so still net positive on paper). Std of avg R (0.21) is ~3x the mean —
      **high variance across instruments, not a uniform edge**: 25th
      percentile already negative (-0.08), 75th percentile solidly positive
      (0.23). Re-checked the 3 validation stocks against this real
      distribution: BHARTIARTL (0.11) ≈ 60th percentile, RELIANCE (0.30) and
      NIFTY (0.31) both upper-quartile — so the hand-picked test stocks were
      reasonably representative, not lucky outliers. **Verdict: the strategy
      is not uniformly good across the universe, so instrument selection
      (ranking) does real work here, same as the other three strategies.**
- [x] `score_for_debit_spread()` added to `strategy_scoring.py` (same file as
      the other four scorers — a shared weighted-percentile-blend utility
      meant to grow, unlike the signal/lifecycle code which is intentionally
      kept in separate parallel modules). Weights median_r_achieved highest
      (not avg_r_achieved) — same median-over-mean preference used throughout
      this project, and what would have caught BHARTIARTL's outlier-reliant
      result (avg 0.11R vs median -0.45R) automatically via the new
      `outlier_reliance_flag`. Filters to ≥30 closed trades, matching the
      credit-spread scorer's own threshold.
- [x] **Extended the backtest window to 2023-01-01 (~31 months, up from
      ~21) and reprocessed the full universe** — moderate extension, not the
      full ~4yr window used for Supertrend, since this is a short-term
      momentum signal and going too far back risks mixing in a less
      representative volatility regime. Result held up well with more data:
      mean avg R unchanged (0.077 → 0.077), but the distribution got
      *tighter*, not wider — std 0.211 → 0.140, min -0.51 → -0.27, fraction
      positive 59.3% → 70.1%. That's the signature of sampling noise
      shrinking with more trades per instrument, not the original result
      being overfit noise (an overfit result would have degraded with more
      data, not gotten cleaner).
- [x] **`score_for_debit_spread()` now returns `(ranked, watchlist)`** —
      instruments below `min_trades` (often recently-listed F&O names like
      SWIGGY with genuinely short histories, not proven-bad performers) were
      silently disappearing from the ranking. Now they surface in a separate
      watchlist (raw stats, no blended score, sorted by avg_r_achieved)
      instead of vanishing — re-check them at the next periodic refresh,
      since their trade count grows on its own as more calendar time passes.
- [x] `src/debit_spread_screener.py` — NEW live screener, parallel to
      `daily_screener.py`, not a modification of it. Same separation of
      concerns as the original: this module only READS whatever the last
      refresh already saved (`exports/debit_spread/{symbol}_trades.csv`) and
      checks for a currently-OPEN trade — a signal that fired recently and
      hasn't yet resolved (stop/target/time-exit). The refresh itself
      happens in `notebooks/10_debit_spread_live_screener.ipynb`, reusing
      `debit_spread_scale_pipeline.process_instrument()` (no duplicate fetch
      code) with a short 120-day lookback — same two-speed cycle as the
      existing screener: notebook 08's deep full-universe refresh keeps the
      ranking honest (~monthly), notebook 10 only refreshes the shortlist
      right before checking. Shortlist = top 15 from
      `RANKING_debit_spread.xlsx` with no `outlier_reliance_flag`, always
      including NIFTY/BANKNIFTY (same pattern as `06_daily_screener.ipynb`).
      Verified against synthetic trades files: correctly finds the OPEN row,
      ignores CLOSED rows, handles a missing/never-refreshed symbol, and
      filters a shortlist down to only the instruments with an active trade.

Stage 9 core pieces are now all built: signal generation, trade lifecycle,
full-universe validation + ranking (with a watchlist for thin-sample names),
and a live screener. Remaining before this could inform real trades: the
underlying-price-proxy limitation still applies — none of this models actual
option premium/IV/theta, a manual options-chain check is still required per
trade same as the other two remaining strategies.

**First live run (notebook 10), confirmed working correctly:** of a 16-name
shortlist, exactly 1 (KPITTECH) had an active trade — consistent with the
math (signal fires ~1-2x/month/instrument, trade holds ~5-8 candles, so any
given stock has roughly a 5-7% chance of being mid-trade at a random moment;
~1 active name out of 16 is the expected value, not a fluke). Entry/stop/
target/current-R all checked out arithmetically against the raw price data.

**Housekeeping (this session):** removed `score_for_long_iron_condor` and
`score_for_directional_buying` (functions, notebooks 13/14, and their stale
`RANKING_*.xlsx` exports) since those two strategies aren't being pursued —
verified nothing else referenced them first. Also removed clearly-superseded
single-stock build/validation notebooks whose logic is now fully reproduced
by the scale pipelines: `08_get_fno_list` (output never read elsewhere —
every notebook calls `get_fno_stock_list(kite)` live instead), and the
original BHARTIARTL walkthrough `02`-`07` plus the debit-spread walkthrough
`20`/`21` (both stocks' data was already regenerated by the later full-scale
runs). Notebook numbering was intentionally left with gaps rather than
renumbered — nothing here references notebooks by number, and gaps already
existed (19 was never used) without causing issues.

## Notes / assumptions log

- Last row per stock in flip exports is an open/ongoing trend, not a real breach —
  exclude when analyzing completed trades.

- **Mean reversion test (tested, not assumed):** Hypothesis was "a trend that has
  already run longer than its own median duration is more likely to revert soon."
  Tested across all 214 F&O instruments with ≥15 closed flips (`src/reversion_test.py`) —
  for flips that crossed their stock's own median duration, the average excess-to-median
  ratio was 1.13–1.15 (median 1.13, mean 1.15), meaning trends that cross their median
  tend to run ~13–15% LONGER than the median again before reversing, not shorter.
  Only the 25th percentile dipped slightly below 1 (0.93); no stock showed strong
  reversion. **Conclusion: trend age is NOT a reversal signal in this data — if anything
  it leans toward mild momentum/continuation.** Do not treat an "aged" trend as a reason
  to enter against it or as a danger signal for entry — it can still be used to widen
  strike distance/reduce size as a conservative sizing choice, but not as a directional bet.

- Screener output (`daily_screener.py`) only reflects data as of the last time a stock's
  raw data was actually refetched via the API (`process_stock`/`fetch_historical_data`).
  `reprocess_all()` recomputes from already-saved data — it does NOT pull new candles.
  Confirmed this gap in practice: ITC showed as DOWN/23-days-old in a stale screener run,
  but a fresh fetch revealed it had already flipped to UP/5-days-old. **Always refresh the
  specific shortlist being traded, same session, before acting on screener output for a
  real entry decision.**

- Two-speed refresh cycle adopted: full-universe refresh (~15–30 min, API-heavy) run
  roughly monthly to keep rankings honest; targeted shortlist refresh (~1–2 min) run
  before any actual trade decision.

- Median preferred over average throughout for duration/adverse-move stats — data is
  outlier-skewed (e.g. a handful of 100+ day trends distort averages); median better
  reflects the "typical" case. Win rate and avg pct_move deliberately excluded from
  premium-selling scores (they measure profitability, not strike-survival — a different
  question); they matter only for the directional buying score.

- Win rate is not a safety indicator for spreads: a stock can have a strong win rate
  while still having a brutal `max_adverse_pct` mid-trend (a trade can dip hard and
  still recover to a "win" by the reversal candle) — `max_adverse_pct`, not win rate,
  drives premium-selling scores.

- Assignment/margin risk is real for single-stock option spreads (American-style) but
  not for index spreads (European-style, no early assignment) — worth remembering when
  comparing risk between stock and index positions.

- Options liquidity (bid-ask spread, open interest) is NOT captured anywhere in this
  project — it's built entirely from underlying price history. A stock can score well
  on historical volatility/movement while having illiquid or untradeable options,
  especially far OTM strikes (discovered via the long IC ranking). Always manually
  check the live options chain before entering, regardless of historical score.

- Earnings/results announcement dates are NOT tracked by this system at all (price-only
  data has no visibility into scheduled corporate events). Always manually check the
  results calendar for any shortlisted stock before entering a position for that month.

- **ADX-rising confirmation needs a window, not an exact-candle match (tested, not
  assumed):** requiring ADX to be higher than N candles ago on the *same* candle as
  the EMA crossover looked reasonable on paper but produced a real 6-month stretch
  (BHARTIARTL, 1H, Feb-Jul 2026) with zero confirmed signals despite dozens of
  crossovers and clearly elevated ADX nearby — ADX tends to peak just before or
  after the EMA cross, not exactly on it. Fixed by allowing confirmation up to
  `confirm_window` candles after the cross (still no lookahead — confirmation only
  looks at data up to the current candle). See Stage 9.

- **Debit spread trade simulation is an underlying-price proxy, not an options
  P&L model:** `debit_spread_trades.py`'s pct_move/R-multiple describe the
  underlying's move, not the actual spread's premium change (which depends on
  IV, theta decay, and strike selection — none of which this project models
  anywhere, same limitation already logged for options liquidity above). A
  target/stop hit on the underlying is a reasonable proxy for "did the
  directional thesis play out," but real P&L will differ. Treat backtest R
  numbers as a filter for signal quality, not an expected-return estimate.