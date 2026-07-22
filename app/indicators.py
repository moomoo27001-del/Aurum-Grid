"""
Local indicator calculations for AURUM_GRID.
All computed locally from OHLCV to avoid burning Twelve Data API credits
(same pattern used in GAIA / AURUM_EA_v3).
"""
import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    return tr.rolling(period).mean()


def atr_percentile(df: pd.DataFrame, period: int = 14, lookback: int = 100) -> float:
    """Where current ATR sits relative to its own recent history (0-100)."""
    atr_series = atr(df, period).dropna()
    if len(atr_series) < lookback:
        lookback = len(atr_series)
    recent = atr_series.tail(lookback)
    current = recent.iloc[-1]
    return float((recent < current).mean() * 100)


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr_ = tr.rolling(period).mean()

    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(period).mean() / atr_)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(period).mean() / atr_)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(period).mean()


def bollinger_band_width_percentile(df: pd.DataFrame, period: int = 20, lookback: int = 100) -> float:
    close = df["close"]
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma

    width = width.dropna()
    if len(width) < lookback:
        lookback = len(width)
    recent = width.tail(lookback)
    current = recent.iloc[-1]
    return float((recent < current).mean() * 100)


def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = true_range(df)
    atr_sum = tr.rolling(period).sum()
    high_max = df["high"].rolling(period).max()
    low_min = df["low"].rolling(period).min()
    ci = 100 * np.log10(atr_sum / (high_max - low_min)) / np.log10(period)
    return ci


def h4_trend_bias(df_h4: pd.DataFrame, fast: int = 20, slow: int = 50) -> str:
    """Reuses AURUM_EA_v3's H4 trend filter concept. Returns 'up', 'down', 'flat'."""
    close = df_h4["close"]
    ema_fast = close.ewm(span=fast).mean().iloc[-1]
    ema_slow = close.ewm(span=slow).mean().iloc[-1]
    diff_pct = (ema_fast - ema_slow) / ema_slow * 100
    if diff_pct > 0.15:
        return "up"
    elif diff_pct < -0.15:
        return "down"
    return "flat"


def build_feature_row(df_h1: pd.DataFrame, df_h4: pd.DataFrame) -> dict:
    """Feature vector consumed by the regime classifier."""
    return {
        "adx": float(adx(df_h1).iloc[-1]),
        "atr_pctile": atr_percentile(df_h1),
        "bb_width_pctile": bollinger_band_width_percentile(df_h1),
        "choppiness": float(choppiness_index(df_h1).iloc[-1]),
        "h4_trend": h4_trend_bias(df_h4),
    }
