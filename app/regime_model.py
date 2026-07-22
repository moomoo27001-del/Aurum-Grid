"""
Regime classifier: ranging vs trending.

Ships with a rule-based fallback so the EA is usable from day one.
Once enough live/historical data has been logged, run train_regime.py
to produce model.json and this module will prefer it automatically —
same "start simple, retrain weekly" pattern as AURUM_EA_v3.
"""
import os
import xgboost as xgb
import numpy as np

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.json")

FEATURE_ORDER = ["adx", "atr_pctile", "bb_width_pctile", "choppiness"]

_model = None
if os.path.exists(MODEL_PATH):
    _model = xgb.XGBClassifier()
    _model.load_model(MODEL_PATH)


def _rule_based(features: dict) -> tuple[str, float]:
    """
    Fallback heuristic, used until model.json exists:
    - ADX < 20 and Choppiness > 55  -> ranging
    - ADX > 25 and Choppiness < 45  -> trending
    - otherwise -> uncertain, treated as trending (safer: don't grid)
    """
    adx_v = features["adx"]
    chop = features["choppiness"]

    if adx_v < 20 and chop > 55:
        return "ranging", 0.65
    if adx_v > 25 and chop < 45:
        return "trending", 0.65
    return "trending", 0.50  # uncertain -> default to caution


def predict_regime(features: dict) -> dict:
    """
    Returns: {"regime": "ranging"|"trending", "confidence": float}
    """
    if _model is not None:
        x = np.array([[features[f] for f in FEATURE_ORDER]])
        proba = _model.predict_proba(x)[0]  # [P(trending), P(ranging)]
        ranging_conf = float(proba[1])
        regime = "ranging" if ranging_conf >= 0.5 else "trending"
        confidence = ranging_conf if regime == "ranging" else 1 - ranging_conf
        return {"regime": regime, "confidence": round(confidence, 3), "source": "model"}

    regime, confidence = _rule_based(features)
    return {"regime": regime, "confidence": confidence, "source": "rule_based"}
