"""
Regime classifier: ranging vs trending.

Unchanged from the original version — the trained model.json expects
exactly these four features. The new fast-momentum check lives as an
independent layer in grid_logic.py rather than being fed into this model,
so we don't need to retrain it to get the fix live.
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
    adx_v = features["adx"]
    chop = features["choppiness"]

    if adx_v < 20 and chop > 55:
        return "ranging", 0.65
    if adx_v > 25 and chop < 45:
        return "trending", 0.65
    return "trending", 0.50


def predict_regime(features: dict) -> dict:
    if _model is not None:
        x = np.array([[features[f] for f in FEATURE_ORDER]])
        proba = _model.predict_proba(x)[0]
        ranging_conf = float(proba[1])
        regime = "ranging" if ranging_conf >= 0.5 else "trending"
        confidence = ranging_conf if regime == "ranging" else 1 - ranging_conf
        return {"regime": regime, "confidence": round(confidence, 3), "source": "model"}

    regime, confidence = _rule_based(features)
    return {"regime": regime, "confidence": confidence, "source": "rule_based"}
