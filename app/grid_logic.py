"""
Translates regime + volatility + trend bias into concrete grid parameters
for the MT5 EA to consume. The EA stays "dumb" (executes what it's told);
all adaptive logic lives here so it can be improved/retrained without
touching MQL5 code.
"""

BASE_SPACING_PIPS = 150       # gold pips (0.01 = 1 pip on most brokers, confirm with your symbol spec)
MAX_GRID_LEVELS = 6
BASE_LOT = 0.01
MAX_LOT_MULTIPLIER = 1.6      # capped scaling, NOT martingale doubling
BASKET_PROFIT_TARGET_PCT = 1.2   # % of account equity
BASKET_TRAIL_TRIGGER_PCT = 0.8
EQUITY_STOPOUT_PCT = 6.0         # hard kill switch


def compute_spacing(atr_pctile: float) -> int:
    """Wider spacing in high-vol regimes, tighter when compressed."""
    if atr_pctile >= 80:
        return int(BASE_SPACING_PIPS * 1.6)
    if atr_pctile >= 60:
        return int(BASE_SPACING_PIPS * 1.3)
    if atr_pctile <= 25:
        return int(BASE_SPACING_PIPS * 0.7)
    return BASE_SPACING_PIPS


def compute_lot_scaling(level: int) -> float:
    """Modest capped scaling per grid level, not classic martingale."""
    scale = 1 + (level - 1) * 0.12
    return round(BASE_LOT * min(scale, MAX_LOT_MULTIPLIER), 2)


def compute_direction_bias(h4_trend: str) -> dict:
    """
    Returns level allocation skew.
    Pure range -> symmetric. Mild trend -> skew levels + spacing against trend.
    """
    if h4_trend == "up":
        return {"buy_levels": 4, "sell_levels": 2, "sell_spacing_multiplier": 1.4}
    if h4_trend == "down":
        return {"buy_levels": 2, "sell_levels": 4, "buy_spacing_multiplier": 1.4}
    return {"buy_levels": 3, "sell_levels": 3}


def build_grid_signal(regime_result: dict, features: dict, news_blackout: bool) -> dict:
    if news_blackout:
        return {"action": "stand_down", "reason": "news_blackout"}

    if regime_result["regime"] != "ranging" or regime_result["confidence"] < 0.55:
        return {"action": "stand_down", "reason": "trending_or_low_confidence", "regime": regime_result}

    spacing = compute_spacing(features["atr_pctile"])
    bias = compute_direction_bias(features["h4_trend"])

    return {
        "action": "deploy_grid",
        "regime": regime_result,
        "spacing_points": spacing,
        "max_levels": MAX_GRID_LEVELS,
        "base_lot": BASE_LOT,
        "lot_scaling": [compute_lot_scaling(i) for i in range(1, MAX_GRID_LEVELS + 1)],
        "direction_bias": bias,
        "basket_profit_target_pct": BASKET_PROFIT_TARGET_PCT,
        "basket_trail_trigger_pct": BASKET_TRAIL_TRIGGER_PCT,
        "equity_stopout_pct": EQUITY_STOPOUT_PCT,
    }
