# Quant — options strategy research (NSE F&O, Zerodha Kite)

Personal research system for selling option spreads on Indian F&O stocks. Advisory
only — it produces lists to act on manually. **Nothing here places orders.**

## Read this first

`README.md` is the source of truth and is written as a stage-by-stage engineering
log (~1000 lines). It records what was built, what was **tested and rejected**, and
why. Before proposing anything, check whether it was already tried:

| Looking for | Read |
|---|---|
| Credit spread strategy, current state | Stages 6, 7, 8b–8f |
| Directional edge / no-edge detection | Stage 8c |
| Single-day move risk, the PIIND incident | Stage 8d |
| The go-to entry list, market context | Stage 8e |
| IV rank gap: realized-vol proxy + forward IV recorder | Stage 8f |
| Short iron condor + its unsolved timing problem | Stage 6, 8e |
| Debit spread (EMA/ADX) | Stage 9 |
| General F&O trend-following (1D, buy/hold/sell equity) | Stages 10, 10b, **10c** (current state) |
| Naked option buying | Stage 11 |
| Paper trading journal (debit spread + option buying, forward-only) | Stage 12 |
| Tested negatives, assumptions | "Notes / assumptions log" at the end |

Git history is also a real reference — commit messages carry the reasoning, not
just the diff.

## How the user works

**Evidence standard is the defining constraint.** This project holds itself to
"tested, not assumed", and documents honest negative results as first-class
findings. Several plausible ideas were built, tested, and thrown away.

- **Do not add untested rules.** Exits are deliberately unmodelled because
  `exhaustion_test.py` found no duration-based signal and profit-target / DTE rules
  have never been tested against this data. Importing convention here is a
  regression, not a feature.
- **Say when something is unvalidated.** Everything in the screener is in-sample
  and descriptive. Label it that way.
- **The signal does not work everywhere — check before acting on a flip.**
  Both the 4H credit-spread screener and the 1D trend-following screener now
  report per-direction edge, because in both universes a large share of
  instruments have no historical edge on the side that is currently open (1D
  trend-following: DOWN flips showed an edge on only 14% of instruments on
  the original 154-symbol universe). A flip is not self-evidently actionable.
  See Stages 8c and 10b.
- **Negative results get written down.** If something is tested and fails, record
  it in the README so it isn't re-proposed later.
- The user reads the final list and acts; they do not want to re-derive the
  reasoning each time. Put explanations in the code and the README, not in chat.

## Daily / monthly routine (credit spreads)

- **Twice daily, 13:20 and 15:35 IST** — `notebooks/06_daily_screener.ipynb`, Run
  All, read the last cell. Or `python scripts/daily_list.py`.
  Only two 4H candles exist per session (09:15, 13:15), so signals change exactly
  twice a day. Running more often reprints identical output.
- **Each morning** — `python scripts/refresh_token.py`. Kite tokens expire
  overnight; this is the one unavoidable manual step.
- **Monthly** — `notebooks/03_scale_all_fno.ipynb` (full refresh, all ~216
  instruments) then `notebooks/05_score_credit_spreads.ipynb` (re-rank).
  Notebook 04 is optional — 05 rebuilds the comparison table itself.
- **Daily, once neither strategy is being traded live yet** —
  `notebooks/23_paper_trading_journal.ipynb`. Refreshes the debit spread +
  option buying shortlists and journals any trade whose signal fired on or
  after paper-tracking's start date. Review after 1-2 months (win rate, avg
  R, total R) before risking real capital on either strategy. See Stage 12.
- **Daily, ~15:45 IST (after quotes settle)** — `python scripts/record_iv_snapshot.py`.
  Records one ATM-IV row per F&O symbol to `logs/iv_history/{symbol}.csv`. Building
  toward a real IV rank (~6 months to a usable percentile); safe to skip a day, but
  every skipped day is a permanently missing data point. See Stage 8f.

## Traps that have actually bitten

- **numpy bool identity.** `numpy.bool_(True) is True` is `False`. Any `is True` /
  `is False` check against a pandas-derived value silently never fires. This has
  caused two separate silent failures. Cast with `bool()`.
- **Excel round-trip of `duration`.** The Flips sheet's `duration` comes back as a
  float in days, not a timedelta — `pd.to_timedelta()` on it collapses everything
  to ~0. Use `exhaustion_test._duration_to_days()`. `reversion_test.py` still
  carries the broken version.
- **Stale Jupyter kernels.** Editing `src/` then re-running a notebook without a
  restart runs the OLD code, and pipelines that WRITE reports will silently produce
  files missing new columns. Notebook 06 has `%autoreload 2`; others do not.
- **Partial-metric scoring.** Adding a scoring term with a flat denominator makes
  rows missing that metric score `NaN` and vanish from the ranking — the output
  still looks complete, just shorter. Use per-row weights.
- **`exports/` and `data/` are gitignored.** Reports are regenerable via
  `reprocess_all(symbols)` — recomputes from saved candles, no API calls, no token.

## Structure

```
src/       flip_analysis, supertrend, summary_stats, monthly_range  (core)
           strategy_scoring        per-strategy rankings
           daily_screener          directional edge + tradeable/watchlist/no_edge
           market_context          buffer-to-flip, beta, sector, realized_vol_rank
           entry_advisor           the final balanced list
           black_scholes           BS pricer + implied_vol solver
           iv_recorder             daily forward ATM-IV snapshot (Stage 8f)
           paper_trading           forward-only journal (Stage 12)
notebooks/ 01 auth · 02 position monitor
           03-07 credit spread (03/04 shared 4H build, 05-06 score+screen, 07 exhaustion test)
           08-09 short IC · 10-13 general F&O trend-following (1D)
           14-16 debit spread · 17-19 option buying · 20-22 exploration/tests
           23 paper trading journal (debit spread + option buying, forward-only)
scripts/   daily_list.py, refresh_token.py, record_iv_snapshot.py
exports/   generated reports + RANKING_*.xlsx   (gitignored)
logs/      run logs, paper_trading_journal.csv, iv_history/{symbol}.csv (tracked in git —
           irreplaceable if lost, unlike exports/ and data/)
```

## Known open items

- **IV rank — the main gap, now in progress (Stage 8f).** Nothing says whether the
  premium at a chosen strike is worth taking. Cannot be backfilled: option tokens
  roll each expiry and expired contracts leave Kite's instrument dump, so the
  historical IV series does not exist on this side. `scripts/record_iv_snapshot.py`
  started recording forward IV daily to `logs/iv_history/{symbol}.csv` — needs ~6
  months before a percentile rank is usable, nothing reads it yet. In the meantime,
  `market_context.realized_vol_rank()` (backfillable, live today) is the interim
  proxy — shown in notebook 06's final list, informational only, no threshold set.
- **Short IC entry timing** — still unsolved. Premium is rich at month-start but
  unconfirmed; confirmation arrives once theta is spent. Trend-freshness was tested
  as a fix (correlation 0.017 over 10,671 symbol-months) and rejected.
- **Earnings / corporate actions** — no source in Kite Connect. Manual.
- **Options liquidity** — deliberately manual, by the user's choice. Do not rank
  on it.
- **Trend-following DOWN side** — `trend_score` (notebook 12) scores only the
  UP side, so DOWN flips are unscored and `signal_works_here` is the only thing
  separating a real DOWN flip from noise. Defensible given DOWN showed an edge
  on just 14% of instruments on the original 154-symbol universe (Stage 10b) —
  not yet re-checked on the full F&O universe (Stage 10c) — but revisit if
  that side is ever traded.
- **1D trend-following stop-loss** — tested (Stage 10c, `src/stop_loss_test.py`)
  and rejected: fixed-%, ATR-multiple, and worst-day-based candidate rules all
  made outcomes worse than holding to the natural DOWN-flip exit. Do not
  re-add one without a new test — this was a real, unambiguous negative
  result, not an oversight.
