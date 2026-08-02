"""
AURUM_GRID signal server.
Endpoints:
  GET  /health
  GET  /news_check   -> debug: current news blackout status + upcoming high-impact USD events
  GET  /grid_signal   -> regime + grid parameters for the MT5 EA to consume
  POST /log_trade     -> logs closed basket outcomes for weekly retraining
  POST /log_regime_outcome -> logs realized regime vs predicted (for retrain accuracy tracking)
"""
import os
import json
from datetime import datetime, timezone
from fastapi import FastAPI
from pydantic import BaseModel

from . import data_feed, indicators, regime_model, grid_logic, news_calendar

app = FastAPI(title="AURUM_GRID Signal Server")

LOG_DIR = os.environ.get("LOG_DIR", "/tmp/aurum_grid_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# London session focus, same lesson learned from AURUM (Asia session unprofitable)
SESSION_START_UTC = int(os.environ.get("SESSION_START_UTC", 7))
SESSION_END_UTC = int(os.environ.get("SESSION_END_UTC", 16))
ENABLE_SESSION_FILTER = os.environ.get("ENABLE_SESSION_FILTER", "true").lower() == "true"

# Don't open new grids too close to the weekend — swap fees over a weekend
# hold, plus gap risk on a still-open basket while markets are closed, can
# wipe out gains. Friday = weekday 4 (Mon=0) in Python's convention.
FRIDAY_CUTOFF_HOUR_UTC = int(os.environ.get("FRIDAY_CUTOFF_HOUR_UTC", 12))


def in_trading_session() -> bool:
    if not ENABLE_SESSION_FILTER:
        return True
    now = datetime.now(timezone.utc)
    if now.weekday() == 4 and now.hour >= FRIDAY_CUTOFF_HOUR_UTC:
        return False  # too close to weekend — don't open new grids
    return SESSION_START_UTC <= now.hour < SESSION_END_UTC


def check_news_blackout() -> bool:
    """
    Blocks grid deployment ±30 min around high-impact USD economic releases
    (NFP, CPI, FOMC, etc.) using the Forex Factory weekly calendar feed.
    """
    return news_calendar.is_blackout()


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": regime_model._model is not None}


@app.get("/news_check")
def news_check():
    """Debug endpoint: shows current blackout status and the raw calendar
    events being evaluated, so you can verify the feed is working without
    waiting for an actual news window."""
    events = news_calendar._fetch_calendar()
    high_impact_usd = [
        {"title": e.get("title"), "date": e.get("date"), "impact": e.get("impact")}
        for e in events
        if e.get("country") in news_calendar.RELEVANT_CURRENCIES and e.get("impact") == "High"
    ]
    return {
        "is_blackout_now": news_calendar.is_blackout(),
        "high_impact_usd_events_this_week": high_impact_usd,
    }


@app.get("/grid_signal")
def grid_signal():
    if not in_trading_session():
        return {"action": "stand_down", "reason": "outside_session_window"}

    news_blackout = check_news_blackout()

    df_m15 = data_feed.get_m15()
    df_h1 = data_feed.get_h1()
    df_h4 = data_feed.get_h4()

    features = indicators.build_feature_row(df_h1, df_h4, df_m15)
    model_features = {k: v for k, v in features.items() if k in regime_model.FEATURE_ORDER}
    regime_result = regime_model.predict_regime(model_features)

    signal = grid_logic.build_grid_signal(regime_result, features, news_blackout)
    signal["features"] = features
    signal["timestamp"] = datetime.now(timezone.utc).isoformat()

    _append_log("grid_signal_log.jsonl", signal)
    return signal


class TradeLog(BaseModel):
    basket_id: str
    open_time: str
    close_time: str
    levels_filled: int
    net_profit: float
    regime_at_open: str
    spacing_points: int
    close_reason: str  # "profit_target" | "trail_stop" | "equity_stopout" | "weekend_flatten" | "manual"


@app.post("/log_trade")
def log_trade(trade: TradeLog):
    _append_log("trade_outcomes.jsonl", trade.dict())
    return {"status": "logged"}


@app.post("/log_regime_outcome")
def log_regime_outcome(payload: dict):
    _append_log("regime_outcomes.jsonl", payload)
    return {"status": "logged"}


def _append_log(filename: str, payload: dict):
    path = os.path.join(LOG_DIR, filename)
    with open(path, "a") as f:
        f.write(json.dumps(payload, default=str) + "\n")
