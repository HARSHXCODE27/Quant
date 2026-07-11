# QUANT — Supertrend Flip Backtester

Analyzes how the Supertrend indicator behaves on F&O stocks over the past 4 years (2022–2026)
on the 4H timeframe: how many times it flipped, in which direction, how long each flip lasted,
how the trailing SL moved, and how far price was from entry when the SL was finally breached.

Live tracking is a **future phase** — current focus is historical backtesting only.

## Tech stack
- Python 3.12 (venv)
- kiteconnect (Zerodha Kite Connect API — historical data)
- pandas / pandas_ta (Supertrend calculation)
- Jupyter notebooks (exploration/verification only)

## Folder structure
```
QUANT/
├── config/
│   └── credentials.py     # API key/secret — NEVER committed (see .gitignore)
├── data/
│   ├── raw/                # raw 4H candles per stock, as pulled from Kite
│   └── processed/          # candles with Supertrend applied
├── src/                    # reusable code — functions imported into notebooks/scripts
│   ├── auth.py
│   ├── fetch_data.py
│   ├── supertrend.py
│   └── flip_analysis.py
├── notebooks/               # exploration + visual verification only, no core logic here
├── exports/                 # final output — one row per flip, per stock
├── logs/
└── README.md
```

## Setup
1. Activate venv: `source .venv/bin/activate`
2. Install deps: `pip install kiteconnect pandas pandas_ta jupyter`
3. Add your API key/secret to `config/credentials.py` (already gitignored — do not commit)
4. Run `git init` + confirm `.gitignore` excludes `config/credentials.py`, `data/`, `.venv/`

## Progress — Stages

### Stage 0 — Project scaffolding ✅
- [x] Folder structure created
- [x] venv set up (Python 3.12.13)
- [x] Kite API credentials obtained
- [ ] git initialized + `.gitignore` in place

### Stage 1 — Data pipeline (single stock)
- [ ] `src/auth.py` — login/session handling
- [ ] `src/fetch_data.py` — pull `4hour` candles for one stock (e.g. NIFTY 50), chunked at 400-day request limits, 2022–2026
- [ ] Raw data saved to `data/raw/`

### Stage 2 — Supertrend application
- [ ] `src/supertrend.py` — apply Supertrend to the 4H data
- [ ] Visually verify against Kite/TradingView chart for the same stock+period

### Stage 3 — Flip detection & trade stats
- [ ] `src/flip_analysis.py` — detect direction flips
- [ ] For each flip: entry price, initial SL, every SL trail update, breach point
- [ ] Compute: duration held, % distance entry→breach (loss / breakeven / locked profit)
- [ ] Export one row per flip to `exports/`

### Stage 4 — Validation
- [ ] Manually cross-check 5–10 flips against the live chart
- [ ] Handle edge cases: SL never breached (still open), data gaps, corporate actions/splits

### Stage 5 — Scale to all F&O stocks
- [ ] Loop Stage 1–3 pipeline across full F&O list
- [ ] Handle rate limits (3 req/sec) and 400-day chunking per stock
- [ ] Aggregate all exports into a single summary table

### Stage 6 — Live tracking (future, not now)
- [ ] Deferred until Stage 5 is complete and validated

## Notes / assumptions log
*(Use this section to record any judgment calls — e.g. how you handle stock splits, which Supertrend
period/multiplier you settled on, etc. Future-you will thank you.)*
