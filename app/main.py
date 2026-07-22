"""
AURUM_GRID signal server.
Endpoints:
  GET  /health
  GET  /grid_signal   -> regime + grid parameters for the MT5 EA to consume
  POST /log_trade     -> logs closed basket outcomes for weekly retraining
  POST /log_regime_outcome -> logs realized regime vs predicted (for retrain accuracy tracking)
"""
import os
import json
from datetime import datetime, timezone
from fastapi import FastAPI
from pydantic import BaseModel

from . import data_feed, indicators, regime_model, grid_logic

app = FastAPI(title="AURUM_GRID Signal Server")

LOG_DIR = os.environ.get("LOG_DIR", "/tmp/aurum_grid_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# London session focus, same lesson learned from AURUM (Asia session unprofitable)
SESSION_START_UTC = int(os.environ.get("SESSION_START_UTC", 7))
SESSION_END_UTC = int(os.environ.get("SESSION_END_UTC", 16))


def in_trading_session() -> bool:
    hour = datetime.now(timezone.utc).hour
    return SESSION_START_UTC <= hour < SESSION_END_UTC


def check_news_blackout() -> bool:
    """
    Placeholder — wire to FRED / an economic calendar source before going live.
    Should return True during a blackout window around high-impact releases
    (NFP, CPI, FOMC) for XAU/USD.
    """
    return False


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": regime_model._model is not None}


@app.get("/grid_signal")
def grid_signal():
    if not in_trading_session():
        return {"action": "stand_down", "reason": "outside_session_window"}

    news_blackout = check_news_blackout()

    df_h1 = data_feed.get_h1()
    df_h4 = data_feed.get_h4()

    features = indicators.build_feature_row(df_h1, df_h4)
    model_features = {k: v for k, v in features.items() if k != "h4_trend"}
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
    close_reason: str  # "profit_target" | "trail_stop" | "equity_stopout" | "manual"


@app.post("/log_trade")
def log_trade(trade: TradeLog):
    _append_log("trade_outcomes.jsonl", trade.dict())
    return {"status": "logged"}


@app.post("/log_regime_outcome")
def log_regime_outcome(payload: dict):
    """EA or a scheduled job posts realized regime (based on forward price action)
    vs what was predicted, so train_regime.py can measure/improve accuracy."""
    _append_log("regime_outcomes.jsonl", payload)
    return {"status": "logged"}


def _append_log(filename: str, payload: dict):
    path = os.path.join(LOG_DIR, filename)
    with open(path, "a") as f:
        f.write(json.dumps(payload, default=str) + "\n")
