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
  - **Real limitation raised and investigated: the ranking is static and can't help time
    ENTRY at the start of a new expiry cycle.** The concern: confirming a stock is actually
    behaving range-bound this month only firms up mid-month, by when a large share of that
    month's theta decay is already spent - the ranking alone gives no earlier signal, and
    doesn't react to what's happening in the market right now. Checked four possible
    fixes before building anything:
    1. **Trend-freshness filter (tested, negative)** - hypothesis: a currently-active 4H
       trend that flipped very recently (fresh directional move) at month-start should
       predict a wider month than a long-stable trend. Tested across 216 instruments,
       10,671 symbol-month observations: correlation between trend age at month-start and
       that month's realized range_pct was 0.017 - essentially zero. Not built; would not
       have helped.
    2. **Recency-weighted ranking (tested, modest positive - built).** Walk-forward test
       (216 instruments, 9,010 symbol-month predictions): a recency-weighted median of
       monthly range_pct (weight = 0.5^(months_ago/halflife), several half-lives tried)
       beat the flat all-time median at predicting the NEXT month's range - mean abs error
       4.87pp → 4.79pp at a 6-month half-life, closer in ~50% of cases vs ~45% for flat.
       Real but modest - doesn't solve the core timing problem, but free with existing
       data, so wired into `score_for_short_iron_condor()` as an additional weighted
       component (`recency_weighted_range_pct`/`recency_weighted_adverse_pct`) alongside
       the existing flat metrics, not replacing them.
    3. **IV rank/percentile (the one that would actually help - scoped, not built yet).**
       Checked directly via the Kite MCP tools: `get_quotes`/`get_ohlc` return LTP, OHLC,
       volume, open interest, and bid/ask depth for options contracts, but NOT implied
       volatility or Greeks. Getting IV means solving it ourselves (Black-Scholes from
       LTP+spot+strike+time-to-expiry), and a proper IV RANK needs a historical IV time
       series - which means reconstructing each month's ATM option's price history per
       symbol, since option instrument tokens roll every expiry (not a continuous series
       like equity). This is the one signal that would genuinely answer "is premium rich
       or cheap right now" independent of price range - but it's a real multi-step build,
       tracked as its own future project, not a quick add-on.
    4. **Earnings-calendar exclusion (parked - no data source).** No corporate-actions/
       earnings-calendar endpoint exists in Kite Connect, and no reliable automated source
       is available in this environment. Stays a manual check (already logged below in the
       assumptions log), same as options liquidity.
  - ~~`score_for_long_iron_condor`~~ and ~~`score_for_directional_buying`~~ — **removed**
    (not needed going forward). Long IC had found a real, unresolved liquidity limitation
    (top-ranked names were mostly small/mid-cap with poor OTM options liquidity —
    historically volatile ≠ tradeable) before it was dropped. Their notebooks
    (`11_score_long_ic.ipynb`, `12_score_directional_buy.ipynb`), functions, and stale
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
- [x] **Honest review of the ranking/filter/screen pipeline (requested directly, not
      assumed to need fixing).** What held up: `score_for_credit_spreads`'s weighting is
      internally consistent for what this actually is (trend-aligned premium selling, not
      range-bound) - low adverse, low fraction of flips reversing within 30 days (favors
      trends outlasting a spread's life), longer median duration, min_flips=30 floor.
      `trend_age_note` correctly avoids over-claiming, since reversion_test.py/
      exhaustion_test.py already tested and found crossing a duration percentile does NOT
      predict reversal. Three real gaps found, two fixed, one flagged as unbuilt:
  - **Screener refresh was inefficient, not destructive (checked directly, unlike the
    other three pipelines).** Notebook 06's refresh cell always used the SAME deep
    `from_date=2022-01-01` window as notebook 03's monthly refresh - so unlike the debit
    spread/option buying/pledged bugs, it was never silently shrinking history. It was
    wasteful though: re-fetching ~4 years of 4H data for a ~16-symbol shortlist on every
    daily run. Added `process_stock_incremental()` to `scale_pipeline.py` (same
    merge-not-replace pattern and shrink-guard as the other three fixes) and switched
    notebook 06 to use it - validated via a mocked fetch test (existing history correctly
    preserved/extended, fresh-symbol path still does a proper deep fetch, guard condition
    correctly detects a shrink scenario) before wiring in.
  - **Screener showed age but not runway - fixed.** `check_trend_status()` told you how
    long a trend had run and whether it crossed past percentile checkpoints, but not the
    more directly useful number: how much of that percentile's "runway" is left right now.
    Added `runway_left_vs_median/p75/p90` (checkpoint minus current age, negative = already
    past it) to `daily_screener.py` - purely descriptive, same tested caveat as the
    booleans it sits alongside (not a reversal/exit signal), just easier to read at a
    glance than three separate True/False flags.
  - **Recency-weighting tested for credit spread's own metrics - real negative result,
    not built.** The same idea that gave short IC a modest improvement (see Stage 6) was
    tested here too, properly, before assuming it would transfer: walk-forward across 216
    instruments, 11,499 flip-level predictions, comparing a flat all-time median against a
    recency-weighted one for `duration_days` and `max_adverse_pct`. Flat median won clearly
    for duration (mean error 14.8 days vs 15.0-17.4 across every half-life tried, 2-12
    months) and was a wash-to-slightly-worse for max_adverse_pct. Likely because these are
    irregular per-flip events, unlike short IC's regularly-sampled monthly range_pct -
    recency-weighting an irregular event stream just amplifies noise from whatever's
    recent rather than capturing real regime drift. Not wired in.
  - **Sector-concentration check remains a real, unbuilt gap.** Confirmed directly against
    a real shortlist run: ICICIPRULI, HDFCBANK, and BANKNIFTY all appeared in the same
    top-15 credit-spread shortlist simultaneously - all financials, with nothing in the
    pipeline flagging it. Stays part of the manual checklist (results dates, sector news,
    IV, concentration) for now - not built this round.

### Stage 8 — Live tracking / automation (future, not started)
- [ ] Only revisit if manual checking becomes a proven, felt bottleneck after real trading

### Stage 8b — Exhaustion test (exit-side, credit spreads) ✅
- [x] `src/exhaustion_test.py` + `notebooks/07_exhaustion_test.ipynb` — different
      question from `reversion_test.py`. That test asks whether an aged trend
      predicts reversal AT ENTRY (no — momentum, ~13-15% longer). This asks,
      for an already-OPEN position: once a trend crosses its own median/75th/90th
      percentile duration, how much MORE time typically remains, and is that
      tightly clustered enough to act on as a profit-booking signal? Pools
      excess as a ratio of the checkpoint (not raw days, to avoid mixing
      stocks of very different typical durations), across all 216 instruments.
- [x] **Verdict: no usable exhaustion signal at any checkpoint (tested,
      honest negative result).** Coefficient of variation (std/mean) sits at
      ~1.0-1.03 at all three checkpoints (median, p75, p90) — the spread of
      "how much longer it ran" is roughly as large as the average itself,
      with no tightening the deeper into the tail. Even at p90, 91.3% of
      crossings still needed up to double the p90 duration again before
      ending. Consistent with (not contradicting) the entry-side finding —
      duration behaves like momentum without a predictable expiry. Per scope,
      no live-check function was built, since none of the three checkpoints
      cleared the bar for "tight enough to act on" — keep managing exits by
      price action/manual judgment, same as before.
- [x] **Found and fixed a real bug while validating, in the NEW file only:**
      `reversion_test.py`'s `pd.to_timedelta(closed["duration"])` assumes a
      timedelta string, but the real `duration` column round-trips through
      Excel as a plain float already in days — `pd.to_timedelta()` on a bare
      float defaults to nanoseconds, silently collapsing every absolute-day
      output to 0.0. Confirmed by running `reversion_test.py` itself against
      real exports (ABB: `median_duration` came back 0.0). The documented
      1.13-1.15 `excess_to_median_ratio` finding above is unaffected — it's a
      pure ratio, so the same broken scaling cancels out top and bottom — but
      `reversion_test.py`'s own per-stock `median_duration`/
      `avg_excess_days_after_median` columns are silently wrong if read
      directly. `exhaustion_test.py` handles both possible reload shapes
      correctly (see its `_duration_to_days` helper). `reversion_test.py`
      itself was deliberately left unmodified — out of scope for this session,
      flagged for a separate fix if wanted.

### Stage 8c — Directional edge, single-day risk, and the go-to entry list ✅
- [x] **Root problem found: `score_for_credit_spreads()` has no profitability term.**
      All five components (median/worst adverse, worst gap, duration, % within a
      monthly cycle) are risk-CONTAINMENT metrics, pooled across BOTH directions.
      So a stock whose UP flips work and whose DOWN flips don't scores exactly like
      one where both work, and the shortlist gave no way to tell them apart. LUPIN
      scored 65.7 while its DOWN side won 33.3% of the time.
- [x] `daily_screener.py` — `_directional_edge()` / `_edge_flag()` / `split_by_edge()`.
      For the side that is actually OPEN: win rate, median move, containment at
      5%/6%, worst adverse/gap/day, % within 30d, plus the OPPOSITE side for
      contrast. Splits the screen into three buckets that need different action:
  - **tradeable** — the open direction has historically worked
  - **watchlist** — wrong half of a good stock; revisit on the flip, don't discard
  - **no edge either side** — the signal has never worked in EITHER direction.
    **This is the case the ranking is structurally blind to**: it scores only how
    well-behaved price is, so KOTAKBANK/GRASIM/HINDUNILVR/ALKEM all scored well
    (86-97% contained, gaps 2.5-3.3%) while being wrong both ways.
  - Nothing is deleted — `no_edge` is returned and printed, same convention as
    `gap_risk_flag`, so the exclusion stays auditable.
- [x] **Containment is primary, win rate secondary — tested, and it matters.**
      A credit spread is a "price won't breach my strike" bet, not a directional
      one. Checked directly by measuring what FADING the signal would look like on
      the 9 watchlist names: the faded direction wins more often (55-68% vs 33-45%)
      but containment at 6% collapses from a mean of 86.7% to 71.4%, with faded
      tail excursions of 19-25% (COLPAL: 100% contained following, 72.4% fading,
      worst 22.74%). **Do not fade the signal with credit spreads** — it optimises
      the metric that doesn't pay and wrecks the one that does. Whether fading
      works as a DEBIT structure is untested and remains open.

### Stage 8d — Single-day move risk (the gap metric's blind spot) ✅
- [x] **Real gap found in production, not in theory.** PIIND was ranked #1 on a live
      shortlist on 2026-08-12 and fell 8.97% that day — its second-worst day in four
      years. `max_gap_against_pct` only measures the OPENING jump (open vs previous
      close), which was just 1.28%; the other 7.79% happened intraday. A near-record
      one-day collapse was invisible to every term in the scorer.
- [x] `flip_analysis.py` — `add_daily_move_column()` plus three per-flip columns:
      `worst_day_against_pct` (day-level analogue of the gap metric),
      `entry_day_move_pct`, and `born_on_outlier_day` (|move| > 4%). Recorded per
      flip rather than derived later, so "do crash-born flips behave differently?"
      stays testable against history.
- [x] `summary_stats.py` + `strategy_scoring.py` — `Worst single-day move against
      (4yr)` scored at weight 2 alongside the other tail-risk terms (denominator
      13 → 15), plus a `day_risk_flag` at >7%.
- [x] **Universe-wide result:** median worst gap 5.39% vs median worst single day
      7.60% — the gap metric was seeing less than half of real single-day risk.
      **42 stocks pass the 5% gap filter but fail a 7% single-day filter.** Biggest
      demotions: PRESTIGE rank 43→75 (gap 4.17%, day 13.21%), PIIND 11→29 (4.07% /
      10.18%), TRENT 96→117 (4.78% / **19.34%**).
- [x] **Live check, not just a historical stat.** `born_on_outlier_day` is surfaced
      on the CURRENTLY OPEN flip and appended to `edge_flag`, because the
      containment stats every strike distance is chosen from are drawn from
      ORDINARY flips and do not describe a trend that began mid-crash.
- [x] **Two bugs found and fixed while building this:**
  - **numpy bool identity, twice.** `numpy.bool_(True) is True` is False, so
    `is True` / `is False` checks against pandas-derived values silently never
    fire. First occurrence left every stock unflagged; second left every
    crash-born flip unwarned. Both now cast with `bool()`. Worth grepping for
    this pattern elsewhere.
  - **Flat denominator poisoned partial data.** The new score term used a single
    weight for all rows, so any stock missing the metric scored `NaN` and vanished
    from the ranking entirely — output still looked complete, just shorter. Now a
    PER-ROW weight: a stock without the metric is scored on its remaining five
    components and marked `scored_without_day_metric`.

### Stage 8e — Market context and the single go-to entry list ✅
- [x] `market_context.py` — the three things `daily_screener.py` could not answer
      because it deliberately reads only `exports/`:
  - `buffer_to_flip_pct` — distance from spot to the Supertrend level that would
    invalidate the open trend. **The most decision-relevant number that was
    missing**: NIFTY sat 0.27% away while topping the containment table, BANKNIFTY
    1.26% and already underwater.
  - `beta_vs_nifty` — so a 50/50 direction split is SHOCK-balanced, not merely
    count-balanced. Three bear calls on defensive FMCG names do not offset three
    bull puts on the index.
  - `sector` — hand-maintained map; unlisted symbols return `UNKNOWN` and are
    skipped by the cap rather than counted as a sector of their own. Closes the
    concentration gap flagged as unbuilt in Stage 7.
- [x] `entry_advisor.py` + `scripts/daily_list.py` — one list, balanced 50/50, with
      a plain-language reason per name built from its own numbers. Filter chain:
      no-edge → wrong-side → crash-born → thin buffer → underwater → sector cap →
      50/50. Every excluded name is reported with the stage that removed it.
- [x] **Sector cap is applied PER DIRECTION.** Concentration risk means positions
      that LOSE TOGETHER — two bull puts in FMCG do, but a bull put on NESTLEIND
      and a bear call on DABUR are opposite bets that partially offset. Capping
      globally treated that hedge as concentration and silently cost the book its
      balance (3 UP / 2 DOWN). Sides also fill by INTERLEAVING, scarcer side first;
      filling UP completely first let it claim shared sectors and starve DOWN.
- [x] **Directional supply is structurally asymmetric.** On 2026-08-12, across all
      89 gap-clean names: 25 UP candidates vs 8 DOWN. DOWN quality falls off a
      cliff after the fifth (setup_score 75.3 / 65.5 / 65.5 / 51.1 / 50.0, then
      38.2 / 29.4 / 16.2). **10-a-side is not reachable**; forcing 8 pulls in
      PRESTIGE at 71.4% containment and a 13.21% worst day. The script reports the
      shortfall rather than quietly forcing in a weak bear call.
- [x] **Exits deliberately NOT built.** `exhaustion_test.py` found no usable
      duration-based exit signal, and profit-target / DTE rules are untested
      against this data. Wiring them in would import folklore into a system
      otherwise held to a tested standard. Exits stay manual.
- [x] **Short iron condor on no-edge names — checked, positive, not built.**
      "No directional edge either way" and "stays in a range" are close to the same
      statement. The 6 no-edge names average an 87th-percentile `short_ic_score`
      (HINDUNILVR 97th, RELIANCE 96th, GRASIM 92nd, KOTAKBANK 90th) vs 76th for
      tradeable. **Not built, deliberately:** it addresses IC stock SELECTION, but
      the open IC problem is entry TIMING (premium is rich at month-start but
      unconfirmed; confirmation arrives once theta is spent). Edge classification is
      a 4-year stock-level property and cannot move month to month, so it is
      structurally incapable of being a timing signal. IV rank remains the answer.
- [x] Notebook 06 restructured to 6 cells: column reference (markdown) → candidates
      → API refresh → full screen → three buckets → **the final list**. Sort key is
      printed above every table. `%autoreload 2` added so a stale kernel can never
      run old module code — the failure that once rewrote 31 reports missing their
      new columns.

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
      happens in `notebooks/16_debit_spread_live_screener.ipynb`, reusing
      `debit_spread_scale_pipeline.process_instrument()` (no duplicate fetch
      code) with a short 120-day lookback — same two-speed cycle as the
      existing screener: notebook 14's deep full-universe refresh keeps the
      ranking honest (~monthly), notebook 16 only refreshes the shortlist
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

**First live run (notebook 16), confirmed working correctly:** of a 16-name
shortlist, exactly 1 (KPITTECH) had an active trade — consistent with the
math (signal fires ~1-2x/month/instrument, trade holds ~5-8 candles, so any
given stock has roughly a 5-7% chance of being mid-trade at a random moment;
~1 active name out of 16 is the expected value, not a fluke). Entry/stop/
target/current-R all checked out arithmetically against the raw price data.

**Housekeeping (this session):** removed `score_for_long_iron_condor` and
`score_for_directional_buying` (functions, notebooks 11/12, and their stale
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

### Stage 10 — Pledged-securities 1D Supertrend screener ✅ (built, not yet run)

> **REPURPOSED in Stage 10c below.** This section is kept as the accurate
> engineering history of how the 1D Supertrend infrastructure was first
> built and validated — it is NOT the current state. The universe, file
> names, and several column names described here have since changed. See
> Stage 10c for what's actually running today.

- [x] New sub-project, separate from the F&O strategies above: a live Supertrend
      screener over the securities actually eligible for pledging as collateral
      (`data/Zerodha - Approved Securities.csv`, 8,265 rows), on the **1D**
      timeframe instead of 4H — same Supertrend logic, different question
      ("is this pledged position's trend still intact") rather than a
      trade-entry signal by default.
- [x] **Cleaned the source file first, then validated the cleaning before
      building anything:** filtered to `security_type` in {Equity, ETF} only
      (dropped Mutual Funds/Government Securities/TBills/Sovereign Gold Bond),
      `haircut_value <= 11`. ETFs were further grouped into 39 themes via a
      keyword classifier (symbol + security_name) since many are near-duplicates
      of each other (12 Gold ETFs, 17 Nifty-50-tracking ETFs, etc.) — grouped
      for the user to pick one per theme, not auto-selected. Final user-curated
      list: 116 shares + 38 ETFs (one per theme, all haircut<=11) — saved at
      `data/processed/Zerodha_Approved_Securities_Cleaned.xlsx`.
- [x] **62 of the 116 pledgeable shares are already in the existing 218-stock F&O
      universe** — checked directly against `exports/*_full_report.xlsx`. This
      is the highest-value starting set: no new signal-generation logic needed,
      same Supertrend flip meaning as the existing credit-spread entries, just
      timed off 1D. The other 54 shares and all 38 ETFs have no listed NSE F&O
      contract of their own (confirmed: NSE doesn't list options on individual
      ETFs, only on ~190 stocks + a handful of indices) — a flip on these means
      something different depending on the instrument:
      - 5 broad-index ETF categories (Nifty 50, Nifty Next 50, Nifty 100, Bank
        Nifty, Sensex) track indices already in the existing 8-index universe —
        the signal should be read off the INDEX itself (no tracking-error drag),
        the ETF's only role is being the thing that's actually pledged.
      - Gold/Silver: no NSE F&O exists on the ETF, but it's a clean,
        already-proven proxy signal for MCX Gold/Silver futures (matches the
        user's existing GOLDCASE-based approach).
      - Everything else (~30 sector/factor/international/bond ETF themes, and
        the 54 non-F&O shares): a flip is informational only — no direct,
        liquid F&O instrument exists to act on it.
- [x] `src/pledged_securities.py` — NEW, loads the 154-symbol universe from the
      cleaned workbook and flags `directly_fno_tradable` per symbol (checked
      against the existing F&O universe, or an optional live list passed in).
- [x] `src/pledged_1d_pipeline.py`, `src/pledged_1d_compare.py`,
      `src/pledged_1d_screener.py` — NEW, parallel to `scale_pipeline.py`/
      `compare_stocks.py`/`daily_screener.py`, **not modifications of them.**
      Reuses `supertrend.py`/`flip_analysis.py`/`monthly_range.py`/
      `summary_stats.py` completely unchanged (all already interval-agnostic).
      Writes to a separate `exports/pledged_1d/` folder and
      `PLEDGED_1D_COMPARISON.xlsx` — **critical**, since `scale_pipeline.py`'s
      export function hardcodes `exports/{symbol}_full_report.xlsx` with no
      interval in the filename; reusing it directly on 1D data would have
      silently overwritten the existing 4H reports for all 62 overlapping
      shares. Verified this doesn't happen (see below).
- [x] `from_date=2015-01-01` used for the scale notebook, deliberately much
      further back than the 4H universe's window — daily candles are ~6x
      coarser than 4H, so flips are proportionally rarer per calendar year;
      recently-listed instruments just get less history automatically, no error.
- [x] Notebooks `12_pledged_1d_scale_all.ipynb`, `13_pledged_1d_compare.ipynb`,
      `14_pledged_1d_live_screener.ipynb` — same full-scale/standalone-compare/
      live-screener three-way split already used for credit spreads and debit
      spread.
- [x] **Verified with synthetic data before handing off** (no live Kite access
      or `pandas_ta` in the build sandbox): generated 750 synthetic daily
      candles, ran a hand-rolled Supertrend equivalent through the REAL
      `detect_flips`/`compute_monthly_range`/`compute_summary_stats` and the
      NEW export/compare/screener functions unchanged. Confirmed the export
      landed in `exports/pledged_1d/` and did NOT create or touch anything in
      the top-level `exports/` folder; confirmed the comparison and screener
      modules correctly read it back. Synthetic test artifacts deleted after.
- [x] **Run against real data (notebooks 12/13):** 140 of 154 instruments
      processed successfully. Real 1D duration stats confirm daily flips run
      much longer than 4H ones, as expected (10-period ATR now spans 10 trading
      days instead of ~1.7): median duration ~49 days, 75th percentile
      ~82-99 days, 90th percentile ~120-146 days (mean pulled up by a handful
      of extreme outliers past 1000 days on thin-flip instruments). 37 of 140
      instruments have fewer than 15 closed flips — same "treat as unproven
      until more calendar time passes" rule as everywhere else in this project.
- [x] **Found and fixed a real bug on first live-screener run:** notebook 14
      originally reused the scale notebook's `from_date=2015` full-history
      window for what should be a short live refresh — fetching ~11 years of
      daily data per symbol with no pause between symbols hit Kite's rate limit
      (`NetworkException: Too many requests`) immediately. Fixed using the real
      duration stats above: refresh window shortened to a rolling 600 days
      (covers the 90th percentile for nearly every instrument, only 2 chunked
      requests instead of ~11), plus a 1-second pause between symbols — same
      `delay_seconds` reasoning already used in every scale pipeline, just
      missing here since a small shortlist made it easy to overlook. Trade-off
      stated plainly in the notebook: an instrument with a currently-open trend
      older than ~600 days will have its reported `trend_age_days` understated
      (truncated to the fetch window) — direction is still correct regardless,
      only the age/percentile-crossing flags could be slightly off in those
      rare cases.
- [x] **The 600-day/1-second fix above wasn't enough — still hit the same rate
      limit on the next run.** Root cause was one level deeper:
      `fetch_data.py`'s `fetch_historical_data()` chunks any request wider than
      ~395 days into multiple calls, with **zero pause between chunks** — Kite's
      historical data endpoint is rate-limited to 3 requests/second (confirmed:
      no separate daily cap). A 600-day window still needs 2 chunks fired back
      to back with no pacing, which can exceed 3/sec on its own regardless of
      the delay between symbols. Fixed in `fetch_data.py` directly (a shared
      file every pipeline in this project uses) by adding a 0.35s pause between
      chunks — only fires when a fetch actually needs 2+ chunks, so every
      existing 4H/1H single-chunk fetch is completely unaffected. This bug was
      always latent for any sufficiently wide window; it just never surfaced
      before because the 4H/1H pipelines' typical windows rarely needed more
      than 1-2 chunks per symbol.
- [x] **Redesigned `14_pledged_1d_live_screener.ipynb` after feedback** — the
      original version refreshed a small hand-picked shortlist live from Kite
      before checking it (same pattern as the debit spread screener). Two
      problems with that for this specific use case: (1) it only checks
      whatever's in the shortlist variable, not the full cleaned universe, and
      (2) it re-fetches from Kite every time, which is exactly what caused the
      rate-limit issue above. Redesigned to do neither: it now just READS
      whatever's already in `exports/pledged_1d/` (populated by notebook 12 /
      `reprocess_all()`, a separate periodic step) for every symbol in the
      cleaned list, and shows two tables — Shares and ETFs — each with
      direction and `trend_age_days`, sorted youngest-first. No live Kite
      calls in this notebook at all, so no rate-limit exposure for daily
      viewing. Of 154 symbols, 140 have a report; 14 (mostly REITs/InvITs —
      EMBASSY, MINDSPACE, INDIGRID, PGINVIT, IRBINVIT, IRB — plus the Liquid
      ETF LIQUIDCASE and a few others) didn't get processed in the first
      notebook 12 run — worth a look next time it's re-run, not yet
      investigated why.
- [x] **Corrected again — read-only was the wrong trade-off.** A screener that
      never re-fetches can go stale the exact same way already documented for
      `daily_screener.py` (ITC once showed DOWN/23-days-old when a fresh fetch
      would've shown UP/5-days-old) — if a symbol flips after the last actual
      fetch, the saved report keeps reporting the old direction/age
      indefinitely, no matter how recently you "check" it. The read-only design
      only existed to dodge the rate-limit bug above; now that the real cause
      (chunk pacing) is fixed, a genuine live refresh of the full 154-symbol
      list is fast enough (short 600-day window, 1-2 paced chunks per symbol,
      a few minutes total) to just do properly. Notebook 14 now runs
      `run_all_instruments(..., force_refresh=True)` across the whole cleaned
      list every time, THEN reports status — same freshness guarantee as
      "always refresh before acting" already established for the credit-spread
      screener, just applied to the full universe instead of a hand-picked
      shortlist.
- [x] **Rate limit hit a third time even with chunk pacing + a 1s between-symbol
      delay** — pacing that sits right at Kite's documented 3 req/sec ceiling
      (~0.35-0.4s spacing) apparently doesn't leave enough real-world margin
      for jitter, and repeated trips of the same limit in one session may add
      a further temporary cooldown on top. Widened the margin instead of
      tuning closer to the edge: window shortened to 390 days (under
      `fetch_data.py`'s 395-day chunk threshold, so every symbol now needs
      exactly ONE request, removing the within-symbol chunk-pacing question
      entirely), and `delay_seconds` raised to a full 1.0s between symbols.
      Slower end-to-end, deliberately — real headroom over cutting it close a
      fourth time.
- [x] **Originally decided NOT to build a ranking/score for this universe —
      reversed once the real purpose was clarified.** The original reasoning
      (no tested exit logic, structurally mixed F&O-tradable/proxy/
      informational universe, ranking implies more trust than earned) was
      sound for "is my collateral's trend still intact," which is what this
      screener was built to answer. But the universe's ACTUAL intended use
      turned out to be different: buy the share/ETF itself on a fresh UP
      flip, exit on the opposite DOWN flip — literal underlying ownership,
      not an options structure. That reframing removes both original
      objections: buying the underlying needs no F&O contract (so the
      mixed-tradability split stops being a scoring blocker — every symbol
      is equally, directly actionable this way), and `flip_analysis.py`'s
      per-flip `pct_move`/`max_adverse_pct` — already computed, unchanged,
      for every historical flip — IS a real, tested trade record for exactly
      this strategy, just never framed as one. See `score_for_pledged_trend_following()`
      below.
- [x] **Real gap found and fixed: notebook 14's live refresh was silently
      shrinking the deep history notebook 12 built.** Discovered while
      building the ranking below — `up_closed_count` (closed UP flips per
      symbol) maxed out at 8 across the whole universe, nowhere near the
      >=15 floor used everywhere else in this project. Root cause: notebook
      12 was calling `run_all_instruments(..., force_refresh=True)` with a
      short 390-day window across the FULL 154-symbol universe on every
      routine run — and `process_instrument()`/`save_raw_data()` do a full
      REPLACE, not an update, so every live check was quietly throwing away
      notebook 12's 2015-onward history and overwriting it with just that
      short window. After repeated runs, every symbol's saved data had
      collapsed to ~1 year (confirmed directly: ABBOTINDIA's raw daily file
      only spanned 2025-07-14 to 2026-08-06 before the fix). Fixed with a
      new `process_instrument_incremental()` in `pledged_1d_pipeline.py`:
      EXTENDS existing saved history with just the recent catch-up window
      instead of replacing it outright (does a genuine deep fetch only the
      first time a symbol has no saved data at all). Verified with a
      mocked-fetch test before trusting it: simulated a short-window live
      refresh against ABBOTINDIA's real 264-row (shrunk) history and
      confirmed the result correctly merged to 401 rows (extended, deduped,
      no gaps) rather than replacing it — confirmed the merge logic works
      before recommending it, not just that it runs. Notebook 14 now uses
      `incremental=True`. This fix only stops the erosion going forward —
      restoring the already-lost deep history required a real re-run of
      notebook 12 (`from_date=2015`, `force_refresh=True`), which was done:
      ABBOTINDIA's raw data now spans 2015-01-01 to present (2,869 rows),
      and `Total flips (closed)` across the universe now ranges 2-90
      (median 56) instead of maxing out at 8.
- [x] `score_for_pledged_trend_following()` added to `strategy_scoring.py` —
      genuinely different from the other four scorers, not a copy with
      renamed columns: those favor either price staying CONTAINED (credit
      spreads/short IC — a premium-selling objective) or a defined-risk,
      ATR-bounded options structure (debit spread/option buying). This
      favors a large favorable move on the UP flips specifically, since
      that's literally what buying the underlying and holding through the
      trend is trying to capture. Built on a new `_add_pledged_up_flip_stats()`
      helper that recomputes real per-symbol stats from CLOSED UP flips only
      (not the blended UP+DOWN columns already in `PLEDGED_1D_COMPARISON.xlsx`
      — a DOWN flip's pct_move describes a trade this strategy never takes).
      Scores the FULL 154-symbol universe (not gated by `directly_fno_tradable`,
      per the reframing above), Shares and ETFs ranked SEPARATELY (own
      percentile scale each) since ETFs structurally have smaller typical
      moves than individual stocks — blending them would make every ETF
      look permanently worse for reasons unrelated to quality. Weights
      `median_pct_move_up` highest, then `win_rate_up_pct`, then
      `median_max_adverse_up` (penalized) — no candles-held/speed component,
      since holding a share/ETF costs no theta, unlike the options
      strategies. `min_flips=15` filters on UP-closed-flip count
      specifically, same floor as everywhere else.
- [x] **`gap_risk_threshold` recalibrated from the inherited 5.0% to 10.0%,
      based on the real data, not a guess.** The 4H credit-spread scorer's
      5% threshold, reused unchanged at first, flagged 94 of 96 ranked
      instruments — nearly everyone, which defeats the point of a flag (it
      should separate candidates, not fire universally). Checked the real
      "Worst single gap (4yr)" distribution across all 140 processed
      instruments: median 6.94%, mean 8.3%, with a clear break between the
      80th percentile (~10%) and 85th (~13.1%). Set the threshold at that
      80th-percentile boundary — now flags 21 of 96 (21.9%), a genuinely
      discriminating minority. Makes sense that 5% was too tight here: it
      was calibrated for the 4H strategies' faster-resolving trades; a 1D
      position held for weeks-to-months will show at least one >5%
      single-day move somewhere in a multi-year history without that being
      unusual.
- [x] **Real run against the restored deep data:** 96 ranked (83 Shares, 13
      ETFs), 44 on the watchlist (below 15 UP-closed flips). Top shares by
      score: AXISBANK, HDFCBANK, TITAN, BAJAJFINSV, LT, TATASTEEL, MARUTI,
      BRITANNIA — median UP-flip moves 2.4-4.7%, win rates 58-68%. Top ETFs:
      MAFANG, MON100, NV20BEES, PVTBANIETF, CONSUMBEES — stronger median
      moves (2.3-7.7%) and higher win rates (60-84%) on a thinner per-
      instrument sample. Saved to `exports/RANKING_pledged_trend_following.xlsx`
      and `exports/WATCHLIST_pledged_trend_following.xlsx`. This directly
      answers the original operational gap that motivated building it: when
      several instruments flip UP the same day, the ranking — not a guess —
      decides which to prioritize. It does NOT decide position sizing/how
      many simultaneous candidates you can actually afford — that's a
      capital-allocation decision this project deliberately doesn't make
      for you, same boundary already established for the other four
      strategies' rankings.

- [x] **`pledged_trend_score` reweighted so the outlier-reliance flag actually
      affects the score, not just labels it.** Real example that surfaced this:
      BAJAJFINSV scored higher than TATASTEEL, but BAJAJFINSV's flagged
      avg-median gap meant its headline average move was propped up by a
      few outlier trades — the typical (median) outcome was actually worse
      than TATASTEEL's. A flag sitting next to an inflated score is
      misleading, not just cosmetic. Added `_score_consistency` (percentile
      rank of `avg_pct_move_up - median_pct_move_up`, lower gap = better,
      same skew_gap the flag is built from) as a real weighted component:
      `pledged_trend_score = (median_move×4 + win_rate×3 + adverse×2 +
      consistency×2) / 11` (previously `/9`, no consistency term). Re-verified
      against real data post-fix (MON100 vs TATASTEEL): MON100 — 80.8% win
      rate, 7.65% median UP move, 3.86% median adverse, no outlier flag,
      scores 79.7. TATASTEEL — 65.8% win rate, 3.76% median move (its 9.68%
      *average* was outlier-inflated, hence the flag), 4.44% median adverse,
      scores 76.0. The score now correctly ranks the more consistent,
      higher-quality trade above the outlier-flattered one.
- [x] **Data-shrinkage regression recurred a second time after the first fix,
      root cause still not fully pinned down — patched with a hard safety
      guard instead of chasing it further.** After `process_instrument_incremental()`
      was deployed and verified, ABBOTINDIA/BAJAJFINSV/LT still ended up back
      down to ~272 rows (2025-07-02 to 2026-08-06) after several back-to-back
      manual reruns of notebook 14's refresh cell in one session, while other
      symbols (TITAN/SBIN/NESTLEIND) kept their full 2015-2026 history —
      inconsistent, data-dependent, not a clean every-run failure (a leading
      tz-related hypothesis was tested directly and disproven). Rather than
      leave this able to silently destroy history again, added a guard to
      `process_instrument_incremental()`: it now compares the merged result's
      earliest date to the existing file's earliest date and **raises an
      error instead of saving** if the merge would shrink history by more
      than 5 days. Converts "silent data loss" into a loud, visible FAILED
      row in the run log. Restored the 3 affected symbols via a full restart
      + re-run of notebook 12; confirmed all back to 2015-2026 (2,869-2,870
      rows) before trusting the ranking again. Practical takeaway: run
      notebook 14's refresh once per session, not repeatedly back-to-back.

### Stage 10b — Directional edge on the pledged 1D universe ✅

> **Also superseded by Stage 10c** — the UP/DOWN edge split and its 54.1%/
> 42.4% numbers below were measured on the 154-symbol pledged universe.
> Kept as history; worth re-measuring on the full F&O universe once enough
> calendar time has passed (flagged as an open item in Stage 10c).

- [x] **The screener reported every flip with equal authority, and the universe
      turns out to be badly asymmetric.** Measured across the 100 pledged
      instruments with >=10 closed flips per side:

      | Side | Mean win rate | Mean median move | % of instruments with an edge |
      |---|---|---|---|
      | UP   | 54.1% | **+0.9%** | **68%** |
      | DOWN | 42.4% | **-1.3%** | **14%** |

      The median DOWN flip ends with price HIGHER than where it flipped.
      **27 of the 100 have no edge in EITHER direction.**
- [x] **Why this matters here specifically.** A DOWN flip is what would prompt
      action on a pledged holding (unpledge, reduce, worry) — and on this
      universe that signal has historically worked on roughly one instrument in
      seven. Of the 48 currently-open DOWN flips, **33 are on instruments where
      the DOWN signal has never worked**; before this change all 48 read
      identically. Mostly it would be selling dips in a long-drift equity
      universe. The UP side is fine — which retrospectively validates notebook
      13's `pledged_trend_score` being UP-only.
- [x] `pledged_1d_screener.py` — ported the directional-edge work from Stage 8c
      (`dir_flips` / `dir_win_rate` / `dir_median_move` / `signal_works_here`,
      plus `opp_win_rate` / `opp_median_move` for contrast). `MIN_DIRECTIONAL_FLIPS`
      is **10** here rather than the 4H screener's 12 — 1D flips are far rarer and
      12 blanked out too many instruments.
- [x] `buffer_to_flip_pct` + `moved_since_entry_pct` — how close price sits to the
      Supertrend level that would reverse the trend. **The most actionable number
      for a holder deciding whether to stay pledged, and it was not visible at
      all** (SHREECEM currently sits 0.38% from invalidating). Reads the saved 1D
      candles, so this module now touches `data/raw/` as well as `exports/`.
- [x] `worst_day` / `entry_day_move` / `born_on_outlier_day` surfaced — these were
      already being WRITTEN to the Flips sheet by the Stage 8d change to
      `flip_analysis.py` (shared, unchanged) but never read back. Free to expose.
      `runway_left_*` added for consistency with the 4H screener.
- [x] **Tested and dropped: ETF whipsaw from tracking error.** `pledged_securities.py`'s
      docstring says broad-index ETF flips "should really be read off the INDEX
      itself, not the ETF", which implied thin ETFs would generate false flips.
      Checked directly: **ETFs whipsaw on 1.8% of flips (duration <=5 days) versus
      1.5% for equities** — no meaningful difference. BANKBEES and JUNIORBEES look
      normal; NIF100BEES is mildly noisy at 8%, but so is DIVISLAB at 7.1%. The
      documented concern is a non-issue in practice and needs no code change.
- [x] Notebook 14 — column reference cell added at the top, and every table now
      prints its sort key above itself.
- [ ] **Open:** `trend_score` (notebook 12) still scores only the UP side,
      so DOWN flips get no score at all and `signal_works_here` is the only thing
      separating a meaningful DOWN flip from noise. Reasonable given the
      asymmetry above, but worth revisiting if the DOWN side is ever traded.

### Stage 10c — Repurposed to a general F&O trend-following screener ✅
- [x] **The real intended use was never about pledging specifically** — Stage
      10's own closing note already said so: buy the share on a fresh UP
      flip, hold, exit on the opposite DOWN flip, literal cash-equity
      ownership. Restricting the universe to the 154 pledgeable
      shares/ETFs was an artifact of where the idea started, not a
      requirement of the strategy. Repurposed the whole sub-project to scan
      the full F&O universe instead — every file in this stage was renamed
      to match (`pledged_securities.py` → `trend_universe.py`,
      `pledged_1d_pipeline.py` → `trend_1d_pipeline.py`,
      `pledged_1d_screener.py` → `trend_1d_screener.py`,
      `pledged_1d_compare.py` → `trend_1d_compare.py`, notebooks 10–13
      renamed to match, `exports/pledged_1d/` → `exports/trend_1d/`,
      `pledged_trend_score` → `trend_score`, `score_for_pledged_trend_following()`
      → `score_for_trend_following()`, `PLEDGED_1D_COMPARISON.xlsx` →
      `TREND_1D_COMPARISON.xlsx`). Function signatures are unchanged; only
      names changed to stop describing a use case this no longer is.
- [x] **New universe**: `src.instruments.get_fno_stock_list()` (~211 stocks,
      confirmed live) plus a new canonical 6-index mapping
      (`src.instruments.INDEX_SYMBOLS` — NIFTY, BANKNIFTY, SENSEX,
      NIFTYNXT50, MIDCPNIFTY, FINNIFTY, matching the same list
      `03_scale_all_fno.ipynb` already uses) — **217 symbols total**, cached
      to `config/trend_universe.csv` so read-only notebooks never need a
      live Kite session. `get_fno_stock_list()` already returns 5 of those
      6 indices as pseudo-stocks (index futures trade on NFO too; SENSEX
      doesn't, its futures are on BFO) — stripped from the stock list and
      re-added as proper `security_type="Index"` rows so nothing is
      double-counted or mistyped.
- [x] **Stop-loss tested before being added anywhere, per this project's own
      standard — and rejected.** New `src/stop_loss_test.py` (same
      methodology as `reversion_test.py`/`exhaustion_test.py`) backtested
      three candidate rule families against every CLOSED UP flip in the 1D
      history: fixed-% thresholds (5/8/10/12/15/18/20%), ATR-multiple
      thresholds (1.5×/2×/2.5×, ATR recomputed from raw daily candles since
      `apply_supertrend()` doesn't expose it), and a `worst_day_against_pct`-
      based trigger (this project's own PIIND finding is that a single bad
      day can matter more than the path getting there). **Every single rule
      made outcomes worse, monotonically, as the threshold tightened** — at
      25%+ no rule ever fired at all and results converged exactly back to
      the no-SL baseline (3,104 pooled UP-closed flips: **mean +5.64%,
      median +0.82%, 54.1% win rate** — matches Stage 10b's UP-side number
      exactly, a good sign the new test computes the same thing correctly).
      The reason: `mean_actual_pct_move_when_stopped` was POSITIVE for every
      rule at every threshold (e.g. a flat 5% stop: flips that got stopped
      out would have averaged **+2.32%** if held instead; an 8% worst-day
      trigger: **+23.97%**). A stop-loss here doesn't cut losses short, it
      cuts recoveries short — consistent with `reversion_test.py`'s
      momentum/continuation finding, not reversion. **No stop-loss was
      added.** Exit is the Supertrend DOWN flip only, by design, not by
      omission — `buffer_to_flip_pct`/`moved_since_entry_pct` remain the
      informational "how close/how underwater" numbers in the live screener.
- [x] **Recalibration checked, not assumed, on the new universe**:
      `gap_risk_threshold=10.0` (still flags 14.4% of the 216-instrument
      universe, in the same "meaningful minority" range as the original
      ~18% target) and `MIN_DIRECTIONAL_FLIPS=10` (median total closed
      flips across the universe is 69, comfortably clearing the floor per
      direction) — both re-verified against the real distribution, neither
      needed changing.
- [x] **Deep 1D history fetched for the full universe**: 216 of 217 symbols
      succeeded (`process_instrument_incremental()`, unchanged — does a
      genuine deep fetch from 2015 for any symbol with no saved data yet,
      incremental catch-up for the rest, so the already-covered overlap
      wasn't re-pulled from scratch). The one failure, `NIFTYFPI`, is a
      niche FPI-focused index product with futures/options on NFO but no
      plain NSE cash/index tradingsymbol to resolve — noted, not chased
      further, same spirit as the handful of REIT/InvIT symbols Stage 10
      already left uninvestigated.
- [x] **Scorer and screener simplified along with the rename**: the
      Shares-vs-ETF split in both `score_for_trend_following()` (two
      separate percentile scales) and the live screener (separate Shares/
      ETF tables) is gone — there are no ETFs in the universe anymore, and
      an index doesn't need its own scoring scale the way a thin sector ETF
      did. Both now rank/report as one unified table; `security_type`
      (`"Stock"`/`"Index"`) is kept purely as a display/filter column.
      Verified live: MIDCPNIFTY and FINNIFTY now rank naturally alongside
      stocks (#5 and #8 by score in one post-rename run) instead of being
      segregated.
- [x] **Orphaned files removed**, since they stopped being reachable by any
      code path the moment the universe changed: the original curated
      workbook (`data/processed/Zerodha_Approved_Securities_Cleaned.xlsx`)
      and its raw source (`data/Zerodha - Approved Securities.csv`), plus 79
      per-symbol reports in `exports/trend_1d/` and 83 raw `_day.csv` files
      in `data/raw/` for symbols that were only ever in the old pledged-only
      universe (mostly ETFs — GOLDCASE, NIFTYBEES, BANKBEES, etc. — and a
      handful of non-F&O shares). All gitignored/regenerable data, not
      source of truth, per this project's own convention.
- [ ] **Open, carried forward from Stage 10b**: the UP/DOWN edge asymmetry
      (54.1%/68% vs 42.4%/14%) was measured on the old 154-symbol universe
      and hasn't been re-checked on the full 217-symbol one yet — worth
      doing once enough calendar time has passed on the newly-added
      symbols' flip history. UP-only scoring remains the right default
      until then.

### Stage 11 — Naked option buying (trailing stop, 1H) ✅
- [x] `src/option_buying_trades.py` — NEW trade-lifecycle module, parallel to
      `debit_spread_trades.py`, not a modification. Reuses the exact same
      signal (`ema_adx_signal.py`, EMA 9/21 + rising-ADX, 1H) unchanged —
      that part never modeled the spread structure, it only ever looked at
      the underlying's price, so it applies identically here.
- [x] **Exit logic is the deliberate difference from the debit spread
      module**, not a copy of it: a debit spread's short leg structurally
      caps the payoff, so a fixed 1.5R target matches that shape. Naked
      buying has no such cap, and the entire point of skipping the hedge
      leg is to keep the uncapped upside on a real trend run — a fixed
      target would throw that away for a strategy that costs MORE (full
      premium, no offsetting short leg reducing theta) for the SAME capped
      return shape as the spread. So this module trails the stop instead:
      same ATR-based initial stop as the debit spread version, but once the
      trade has moved `trail_activate_r` (default 1.0) times the initial
      stop distance in its favor, the stop starts trailing the best price
      seen since entry by the same ATR distance, ratcheting one-way only.
      Before trailing activates, the only exits are the initial stop or the
      time exit — there is no fixed target to hit. Time exit (14 candles,
      same default) is kept as a safety net regardless, since theta still
      bleeds on a naked long option even before trailing kicks in.
- [x] `src/option_buying_screener.py` — NEW live screener, parallel to
      `debit_spread_screener.py`, same read-only-from-last-refresh design.
      Same output shape requested: `candles_held`,
      `candles_left_before_time_exit`, `current_pct_move`, `current_r`, plus
      `current_stop_price`/`trailing_activated` in place of the spread
      screener's fixed `target_price`.
- [x] **Validated on the same 3 stocks used to build the debit spread
      strategy (BHARTIARTL/RELIANCE/NIFTY, 1H)** — same entries as the
      debit spread backtest by construction (shared signal), only the exit
      differs. BHARTIARTL (32 trades): win rate 53.1% vs debit spread's
      50%, avg R 0.22 vs 0.13 — and median R flipped from -0.45 (the debit
      spread's known outlier-reliant result) to +0.06, meaningfully
      reducing that outlier-reliance since bigger winners (2.15R, 2.92R
      seen in this run) are no longer capped at 1.5R.
- [x] `src/option_buying_scale_pipeline.py` — NEW batch runner, parallel to
      `debit_spread_scale_pipeline.py`, same resume/failure-isolation/
      rate-limit discipline, plus a `reprocess_all()` for recompute-only
      refreshes off already-saved 1H data (shared raw files with the debit
      spread pipeline, same interval).
- [x] **Ran the full universe (214 instruments, same Nov 2024–Aug 2026
      window and ≥15-closed-trades floor as debit spread) — PRE-4H-filter
      numbers, superseded further down this stage once the hard filter was
      added:** 189/214 qualified. 72.5% showed a positive avg_r_achieved (vs
      debit spread's 70.1% after its own window extension). Mean avg R
      0.126, median 0.100 — both higher than debit spread's mean 0.077. Std
      0.224 (vs debit spread's tightened 0.140) — more variance across
      instruments, which tracks: a trailing exit is more path-dependent
      than a fixed target. On the 189 symbols common to both strategies,
      option buying beat debit spread on avg_r for 61.9% of them — a real
      edge on average, not uniform. On average 47.9% of entries ever reach
      trail-activation; the rest resolve via the initial stop or the time
      exit without ever getting the chance to trail.
- [x] **Caveat carried over from the debit spread module, and weaker here,
      not stronger:** this still only simulates the underlying's price move
      as a proxy for real trade P&L. That proxy was already imperfect for a
      spread; it's weaker for naked buying, since a naked long option has
      full exposure to theta decay and IV changes with nothing offsetting
      it (a spread's short leg absorbs part of both). Treat these R numbers
      as a signal-quality filter, not an expected real return.
- [x] **This full-universe run used a hand-rolled stand-in for `pandas_ta`
      (exact same formulas — Wilder-smoothed ATR/ADX, standard EMA), not
      the real library** — `pandas_ta` isn't installable in the sandbox
      this was built in (Python version mismatch). The formulas match the
      library's actual implementation, and the run was against real cached
      1H price data (not synthetic), so the results should be representative
      — but worth a from-source rerun via the real library in the normal
      notebook environment before fully trusting the exact numbers, same
      as any sandbox-computed result in this project.
- [x] **`apply_4h_trend_filter()` — HARD FILTER added to `option_buying_trades.py`
      after a tested finding.** Question was: does a 1H entry that agrees
      with the symbol's own currently-active 4H Supertrend direction do
      better than one that opposes it? Tested by joining every closed 1H
      trade to the 4H flip that was open at its entry timestamp (reads the
      same `exports/{symbol}_full_report.xlsx` every other strategy in this
      project already produces — not a new signal, a filter on an existing
      one). Across 12,608 real closed 1H trades (214 instruments) matched to
      a 4H trend state: aligned entries won 53.3% vs 47.2% against, mean R
      0.166 vs 0.024, and — the number that actually mattered — median R
      flipped from +0.08 (aligned) to -0.46 (against). The typical
      against-trend trade lost; the typical aligned trade didn't. Effect
      size was large enough (especially the median flip) that it's unlikely
      to be pure confounding, though it hasn't been checked instrument-by-
      instrument, only pooled.
- [x] Wired in as a **hard filter**, not a soft flag: `apply_4h_trend_filter()`
      zeroes out any 1H signal whose direction disagrees with the 4H
      direction active at that candle, called inside
      `option_buying_scale_pipeline.process_instrument()` and
      `reprocess_instrument()` right after `detect_signals()`, before
      `simulate_trades()`. A signal with no matching 4H flip window (missing
      4H history for that symbol/date) is dropped, not assumed aligned —
      conservative by design. The surviving `four_h_direction` is recorded
      in each trade row for audit, even though by construction every
      surviving trade is aligned.
- [x] **Rerun the full universe with the filter active:** roughly halved
      signal frequency, as expected (an entry only survives if it agrees
      with the 4H trend, and pre-filter alignment was close to 50/50).
      153 instruments now qualify at >=15 closed trades (down from 189
      pre-filter), but the survivors are meaningfully better: 70.6% positive
      avg R (vs 72.5% pre-filter — comparable), mean avg R 0.198 (vs 0.126),
      median 0.170 (vs 0.100), mean win rate 54.9% (vs 51.1%). Std widened
      (0.327 vs 0.224) since each instrument now averages ~19 closed trades
      instead of ~27+ — a thinner, noisier per-instrument sample, which is
      exactly why the ranking below matters even more post-filter, not less.
- [x] `score_for_option_buying()` added to `strategy_scoring.py` — same
      weighting as `score_for_debit_spread` (median_r_achieved highest, same
      `outlier_reliance_flag`), but **`min_trades=20`, not 30** — the 4H
      filter's halved trade frequency means a 30-trade bar would leave
      nothing ranked (post-filter max is 27 closed trades per instrument).
      Rerun post-filter: 51 ranked, 102 on the watchlist (15-19 trades,
      still real, just thinner). Saved to `exports/RANKING_option_buying.xlsx`
      and `exports/WATCHLIST_option_buying.xlsx`.
- [x] Notebooks `17_option_buying_scale_all.ipynb`,
      `18_score_option_buying.ipynb`, `19_option_buying_live_screener.ipynb` —
      same three-way split already used for debit spread (08/09/10).
      Notebook 17 is written to do a **real, clean full refresh**
      (`from_date=2023-01-01`, `force_refresh=True`, same window as debit
      spread's notebook 14) rather than reuse the sandbox run's numbers
      directly — the sandbox run pulled from whatever 1H history happened
      to already be cached per symbol (some files still had the full
      2023-2026 range, others had been shrunk to a few months by later
      short-window live-refreshes), so it's a real but not perfectly
      uniform comparison. Run notebook 17 for the authoritative version
      once Kite access is available.

- [x] **The pledged-securities data-shrinkage regression had an unfixed twin
      in this pipeline too, found via a corrupted trades file.** Notebook
      19's live-screener refresh cell called `process_instrument()` (full
      replace) with a short 120-day lookback for whatever's in its top-20
      shortlist — every run of notebook 19 was silently overwriting
      notebook 17's deep 2023-2026 1H history for any shortlisted symbol
      with just that 120-day window, same class of bug as
      `pledged_1d_pipeline.py`'s, just never ported over here. Surfaced when
      `ADANIENSOL_trades.csv` came back as a 1-byte empty file (`EmptyDataError`
      in the screener) — the shrunk 120-day window barely had enough signals
      to simulate, and `save_trades()` on an empty trades DataFrame writes a
      near-blank file. Confirmed directly: ADANIENSOL/KPITTECH/BSE (that
      day's shortlist) had collapsed from 6,194 rows (2023-2026) to 570 rows
      (Apr-Aug 2026) right after notebook 17 had correctly saved them deep.
      Fixed the same way as the pledged pipeline: added
      `process_instrument_incremental()` to `option_buying_scale_pipeline.py`
      (merges the quick catch-up window onto existing history instead of
      replacing it, refuses to save if the merge would shrink history) and
      switched notebook 19's refresh cell to use it instead of
      `process_instrument()`. Any symbol shrunk before this fix needs a
      re-run of notebook 17 to restore its deep history.

- [x] **Same regression found and fixed a third time — this time it was the
      original source.** A final audit (before closing out this round of
      work) checked every other live-screener notebook for the same
      pattern. Credit spreads (`06_daily_screener.ipynb`) and short iron
      condor (`09_short_ic_shortlist.ipynb`) refetch a full deep window
      every run too, which is wasteful but not destructive — no bug there.
      But `16_debit_spread_live_screener.ipynb`'s refresh cell had the
      identical bug: `process_instrument()` (full replace) called with a
      120-day window for its shortlist. Its own earlier run is actually
      what FIRST shrank ADANIENSOL/KPITTECH/BSE's shared 1H raw file (debit
      spread and option buying read/write the same
      `data/raw/{symbol}_60minute.csv`) — meaning notebook 16 introduced
      the corruption that notebook 19 then re-triggered later. Fixed the
      same way: added `process_instrument_incremental()` to
      `debit_spread_scale_pipeline.py` and switched notebook 16 to use it.
      All three live-screener pipelines that do a "refresh shortlist then
      check" pattern (pledged-1D, option buying, debit spread) now merge
      instead of replace, with the same shrink-guard in each.

## Notes / assumptions log

- **The data-shrinkage regression recurred a FOURTH time even after three separate
  per-pipeline fixes - moved the guard to the shared save function instead.** Each
  earlier fix (pledged-1D, debit spread, option buying) added an incremental
  merge function with its own shrink-guard, but that only protects if that exact
  function is what actually runs. It recurred again in option_buying's ADANIENSOL
  (raw 1H data collapsed 6,194 → 574 rows) even with the fix in place and verified
  correct on disk - root cause was almost certainly a stale Jupyter kernel running
  an old cached version of the module that never called the new incremental
  function at all, bypassing its guard entirely (same class of stale-kernel issue
  already hit multiple times this session, e.g. the `process_instrument_incremental`
  ImportError that needed a kernel restart to resolve). Rather than add a fourth
  per-pipeline patch that has the same blind spot, moved the protection into
  `fetch_data.py`'s `save_raw_data()` - the ONE function every pipeline
  (scale_pipeline, debit_spread_scale_pipeline, option_buying_scale_pipeline,
  pledged_1d_pipeline) actually calls to persist raw price data. Before
  overwriting, it now compares the new data's earliest date against the existing
  file's earliest date and refuses to save (raises) if the new data would start
  more than 5 days later - impossible to bypass by calling an older function, an
  un-restarted kernel, or any future pipeline that forgets its own check.
  `allow_shrink=True` overrides deliberately if ever needed. A corrupted/
  unreadable existing file is treated as nothing-to-protect (self-heals on the
  next successful save, rather than blocking forever). Validated with 5 direct
  file-based tests before trusting it: first save, legitimate extend, shrink
  correctly blocked, override works, corrupted-file self-heal - all passed.

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

- **Exhaustion test (tested, not assumed) — separate question from the one above:**
  the reversion test above is about ENTRY (does an aged trend predict reversal?
  no). This tested EXIT: once an already-open trend crosses its own median/75th/90th
  percentile duration, is the ADDITIONAL time remaining tightly clustered enough to
  use as a profit-booking signal? Tested across all 216 F&O instruments
  (`src/exhaustion_test.py`), pooling excess as a ratio of each checkpoint (not raw
  days — avoids mixing a 10-day-median stock with a 60-day-median stock and misreading
  scale difference as scatter). Coefficient of variation (std/mean) came out ~1.0-1.03
  at all three checkpoints, with no tightening deeper into the tail — even at the p90
  checkpoint, 91.3% of crossings still needed up to double the p90 duration again
  before actually ending. **Conclusion: no usable exit-side exhaustion signal exists at
  any checkpoint — an honest negative result, not a signal forced where none is there.**
  Keep managing exits by price action/manual judgment; do not build a live "exhaustion
  warning" off pure duration data. (Also surfaced a real, separate bug while building
  this: `reversion_test.py`'s duration parsing silently zeroes out its own per-stock
  day columns on real exported data, though the ratio-based headline finding above is
  unaffected — see Stage 8b.)

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

- **1H entries that agree with the 4H trend beat ones that oppose it
  (tested, not assumed) — now a hard filter in option_buying_trades.py:**
  hypothesis was "does a naked-buying signal do better when it agrees with
  the underlying's own 4H Supertrend direction at that moment?" Tested by
  joining 12,608 real closed 1H trades (214 instruments, pre-filter run) to
  the 4H flip that was active at each trade's entry timestamp. Aligned
  trades: 53.3% win rate, mean R 0.166, median R +0.08. Against-trend
  trades: 47.2% win rate, mean R 0.024, median R -0.46. The median flip is
  the one that matters most (same median-over-mean standard as everywhere
  else in this project) — the typical against-trend trade lost money, the
  typical aligned trade didn't. Wired in as `apply_4h_trend_filter()`, a
  hard filter (zeroes the signal, not a soft warning) applied before
  `simulate_trades()`. Roughly halved trade frequency post-filter, as
  expected (pre-filter alignment was close to 50/50), but the surviving
  trades are meaningfully better across the board (see Stage 11 for the
  full before/after numbers). Caveat: tested pooled across the universe,
  not checked instrument-by-instrument — some confounding (certain stocks
  simply trending persistently on both timeframes at once) is possible,
  though the size of the median-R flip makes it unlikely to explain the
  whole effect.

- **Debit spread trade simulation is an underlying-price proxy, not an options
  P&L model:** `debit_spread_trades.py`'s pct_move/R-multiple describe the
  underlying's move, not the actual spread's premium change (which depends on
  IV, theta decay, and strike selection — none of which this project models
  anywhere, same limitation already logged for options liquidity above). A
  target/stop hit on the underlying is a reasonable proxy for "did the
  directional thesis play out," but real P&L will differ. Treat backtest R
  numbers as a filter for signal quality, not an expected-return estimate.