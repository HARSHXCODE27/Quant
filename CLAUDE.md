# Quant — options strategy research (NSE F&O, Zerodha Kite)

Personal research system for selling option spreads on Indian F&O stocks. Advisory
only — it produces lists to act on manually. **Nothing here places orders.**

## Read this first

`README.md` is the source of truth and is written as a stage-by-stage engineering
log (~1000 lines). It records what was built, what was **tested and rejected**, and
why. Before proposing anything, check whether it was already tried:

| Looking for | Read |
|---|---|
| Credit spread strategy, current state | Stages 6, 7, 8b–8e |
| Directional edge / no-edge detection | Stage 8c |
| Single-day move risk, the PIIND incident | Stage 8d |
| The go-to entry list, market context | Stage 8e |
| Short iron condor + its unsolved timing problem | Stage 6, 8e |
| Debit spread (EMA/ADX) | Stage 9 |
| Pledged 1D screener | Stage 10 |
| Naked option buying | Stage 11 |
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
- **Monthly** — `notebooks/02_scale_all_fno.ipynb` (full refresh, all ~216
  instruments) then `notebooks/04_score_credit_spreads.ipynb` (re-rank).
  Notebook 03 is optional — 04 rebuilds the comparison table itself.

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
           market_context          buffer-to-flip, beta, sector
           entry_advisor           the final balanced list
notebooks/ 01-07 credit spread + short IC · 08-11 debit spread · 12-14 pledged
           15-18 option buying · 50-52 exploration/tests
scripts/   daily_list.py, refresh_token.py
exports/   generated reports + RANKING_*.xlsx   (gitignored)
```

## Known open items

- **IV rank — the main gap.** Nothing currently says whether the premium at a
  chosen strike is worth taking. Cannot be backfilled: option tokens roll each
  expiry and expired contracts leave Kite's instrument dump, so the historical IV
  series does not exist on this side. The practical path is to start recording IV
  forward now and have a usable percentile in ~6 months; realized-vol rank is a
  backfillable interim proxy.
- **Short IC entry timing** — still unsolved. Premium is rich at month-start but
  unconfirmed; confirmation arrives once theta is spent. Trend-freshness was tested
  as a fix (correlation 0.017 over 10,671 symbol-months) and rejected.
- **Earnings / corporate actions** — no source in Kite Connect. Manual.
- **Options liquidity** — deliberately manual, by the user's choice. Do not rank
  on it.
