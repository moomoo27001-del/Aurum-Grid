"""
Translates regime + volatility + trend bias into concrete grid parameters
for the MT5 EA to consume.

Changes from v1 (after two live losses caused by fast intraday trends the
H4 filter couldn't see):
- Wider base spacing, fewer max levels — reduces how fast a directional
  move burns through the grid.
- Higher regime confidence threshold (0.55 -> 0.65).
- Hard stand-down on strong fast M15 momentum, independent of what the
  regime classifier says — a second, faster-reacting safety layer.
- Direction bias now also considers the fast M15 signal, not just H4.
"""

BASE_SPACING_PIPS = 250       # widened from 150 — was too tight for recent volatility
MAX_GRID_LEVELS = 4           # reduced from 6 — less exposure per basket
BASE_LOT = 0.01
MAX_LOT_MULTIPLIER = 1.6
BASKET_PROFIT_TARGET_PCT = 1.2
BASKET_TRAIL_TRIGGER_PCT = 0.8
EQUITY_STOPOUT_PCT = 6.0

MIN_REGIME_CONFIDENCE = 0.65  # raised from 0.55 — needs to be more certain

# If the M15 fast-momentum check shows a move bigger than this in either
# direction, stand down entirely regardless of regime classification —
# this is what would have stopped both of the live losses seen so far.
FAST_MOMENTUM_HARD_STOP_PCT = 0.7


def compute_spacing(atr_pctile: float) -> int:
    if atr_pctile >= 80:
        return int(BASE_SPACING_PIPS * 1.6)
    if atr_pctile >= 60:
        return int(BASE_SPACING_PIPS * 1.3)
    if atr_pctile <= 25:
        return int(BASE_SPACING_PIPS * 0.7)
    return BASE_SPACING_PIPS


def compute_lot_scaling(level: int) -> float:
    scale = 1 + (level - 1) * 0.12
    return round(BASE_LOT * min(scale, MAX_LOT_MULTIPLIER), 2)


def compute_direction_bias(h4_trend: str, fast_trend: str) -> dict:
    """
    Combines the slow H4 context with the fast M15 signal. If they agree,
    skew harder in that direction. If the fast signal shows movement the
    H4 filter hasn't caught up to yet, trust the fast signal — it's more
    likely to reflect what's actually happening right now.
    """
    # Fast signal takes priority when it shows real movement — it's what
    # was missing before and directly caused both live losses.
    effective_trend = fast_trend if fast_trend != "flat" else h4_trend

    if effective_trend == "up":
        return {"buy_levels": 4, "sell_levels": 1, "sell_spacing_multiplier": 1.5}
    if effective_trend == "down":
        return {"buy_levels": 1, "sell_levels": 4, "buy_spacing_multiplier": 1.5}
    return {"buy_levels": 2, "sell_levels": 2}


def build_grid_signal(regime_result: dict, features: dict, news_blackout: bool) -> dict:
    if news_blackout:
        return {"action": "stand_down", "reason": "news_blackout"}

    momentum = features.get("fast_momentum_pct", 0.0)
    if abs(momentum) >= FAST_MOMENTUM_HARD_STOP_PCT:
        return {
            "action": "stand_down",
            "reason": "fast_momentum_hard_stop",
            "fast_momentum_pct": momentum,
        }

    if regime_result["regime"] != "ranging" or regime_result["confidence"] < MIN_REGIME_CONFIDENCE:
        return {"action": "stand_down", "reason": "trending_or_low_confidence", "regime": regime_result}

    spacing = compute_spacing(features["atr_pctile"])
    bias = compute_direction_bias(features["h4_trend"], features.get("fast_trend", "flat"))

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
        "fast_momentum_pct": momentum,
    }
