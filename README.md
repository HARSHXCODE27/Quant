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
- [x] `strategy_scoring.py` — four scoring functions, each a weighted percentile blend
      of metrics chosen specifically for that strategy's actual risk profile:
  - **`score_for_credit_spreads`** — favors trend persistence & low adverse movement.
    High priority: median max_adverse_pct, % completed within 30 days, median duration.
    Medium: worst max_adverse_pct, worst gap. Filter: ≥30 flips. Flags (doesn't exclude)
    stocks with worst gap >5%.
  - **`score_for_short_iron_condor`** — favors range containment, quick-reverting trends.
    High priority: median monthly range, median adverse, worst monthly range (all lower =
    better). Duration weighting flipped vs credit spreads (shorter = better). Stricter gap
    flag threshold (>4%).
  - **`score_for_long_iron_condor`** — inverse of short IC; favors high volatility/big moves.
    ⚠ Real limitation found: top-ranked names were mostly small/mid-cap with poor OTM
    options liquidity — historically volatile ≠ tradeable for this strategy. Not fixed in
    scoring (would need live options-chain OI/spread data, not available historically);
    treated as a mandatory manual liquidity check before any long IC trade.
  - **`score_for_directional_buying`** — only strategy where win rate & avg pct_move matter
    (option buying needs the trend to actually pay off, unlike premium selling where
    strike-survival is the goal regardless of win rate). Originally built with a
    hardcoded, approximate NIFTY 50 liquidity filter — later re-run with
    `liquid_universe=None` for the full F&O universe per actual requirement.

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

### Stage 9 — Separate project: dedicated option-buying signal (future, not started)
- [ ] 4H Supertrend is appropriate for credit spreads/IC (lag-tolerant is a feature) but
      likely wrong for option buying (lag directly costs premium/time decay). Would need
      a faster indicator and/or shorter timeframe, and a different trade-definition logic
      (target/stop-based exits, not just "hold until opposite flip"). Scoped as a genuinely
      separate stage, not a retrofit of existing Supertrend flips.

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