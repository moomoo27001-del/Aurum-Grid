# AURUM_GRID

ML-regime-gated grid trading bot for XAU/USD. Same architecture pattern as your other bots:
Railway-hosted FastAPI signal server + Twelve Data feed + local indicator calculation +
an MT5 EA that executes what the server tells it.

## How it differs from AURUM_EA_v3
AURUM_EA_v3 is directional (one entry per signal). AURUM_GRID instead:
1. Uses an XGBoost regime classifier (ranging vs trending) as a **gate** — it only
   deploys a grid when the market is classified as ranging with sufficient confidence.
2. When deployed, grid spacing is set dynamically from ATR percentile, and grid levels
   are skewed toward the H4 trend direction (reusing your existing trend-filter logic)
   rather than running a purely symmetric grid.
3. Lot sizing scales modestly per level (capped at 1.6x base), not classic martingale.
4. The whole basket is managed as a unit: profit target %, trailing stop after target
   is first hit, and a hard equity-based stopout — independent from AURUM's per-trade
   SL/TP.

## Setup
1. `pip install -r requirements.txt`
2. Set environment variables (Railway dashboard or `.env` locally):
   - `TWELVE_DATA_API_KEY` — recommend a **separate** Twelve Data account/key from
     your other bots, consistent with your existing per-bot API isolation.
   - `LOG_DIR` (optional, defaults to `/tmp/aurum_grid_logs`) — for persistent logging
     on Railway, mount a volume or point this at one.
   - `SESSION_START_UTC` / `SESSION_END_UTC` (optional) — defaults to 07:00–16:00 UTC
     (London focus, same lesson learned from AURUM's Asia-session underperformance).
3. Run locally: `uvicorn app.main:app --reload`
4. Deploy to Railway: push this repo, Railway will pick up `Procfile` automatically.

## Before going live
- **Regime model**: ships with a rule-based fallback (`app/regime_model.py`) so it's
  usable immediately. Once you've got a few thousand H1 bars logged, run:
  `python -m app.train_regime --lookback_bars 5000 --forward_window 12`
  This self-labels ranging/trending from realized forward price action — no manual
  labeling needed — and writes `app/model.json`, which the server will prefer automatically.
- **News blackout**: `check_news_blackout()` in `main.py` is currently a stub always
  returning `False`. Wire this to an economic calendar (FRED or otherwise) before
  live trading — grids and NFP/CPI/FOMC gaps don't mix.
- **MQL5 JSON parsing**: the EA uses minimal string-based field extraction to keep the
  skeleton dependency-free. Swap in a proper JSON library (e.g. JAson.mqh) before
  live deployment — the current parser is fine for the fixed field set here but is
  not robust to malformed/reordered JSON.
- **WebRequest allowlist**: add your Railway URL to
  MT5 Tools → Options → Expert Advisors → "Allow WebRequest for listed URL".
- **Backtesting**: grid strategies are notoriously easy to over-fit and easy to
  misjudge in a standard MT5 tester (pending order fill assumptions, spread
  modeling). Recommend forward-testing on a demo account for at least a few weeks
  before committing real size, same as your AURUM live-debugging process.

## Hard limits baked in (do not remove without a reason)
- `MAX_GRID_LEVELS = 6`
- `MAX_LOT_MULTIPLIER = 1.6` (no martingale doubling)
- `EQUITY_STOPOUT_PCT = 6.0` — closes entire basket regardless of individual level P/L

## Feedback loop
`POST /log_trade` — called by the EA when a basket closes, logs outcome + regime +
spacing for later analysis.
`POST /log_regime_outcome` — for tracking realized regime accuracy over time, feeds
into retraining decisions.
