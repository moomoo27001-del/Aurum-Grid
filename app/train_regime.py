"""
Trains the ranging/trending regime classifier.

Labeling approach (no manual labeling needed):
For each historical H1 bar, look FORWARD N bars. If price stayed within a
tight range (max excursion < threshold * ATR), label = ranging (1).
If price trended clearly beyond that band, label = trending (0).
This is the same self-labeling approach that works well for regime models
since it uses realized future price action as ground truth.

Usage:
    python -m app.train_regime --lookback_bars 5000 --forward_window 12
"""
import argparse
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from . import data_feed, indicators


def label_regime(df: pd.DataFrame, forward_window: int, range_threshold_atr: float = 1.5) -> pd.Series:
    atr_series = indicators.atr(df)
    labels = []
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for i in range(len(df)):
        if i + forward_window >= len(df) or pd.isna(atr_series.iloc[i]) or atr_series.iloc[i] == 0:
            labels.append(np.nan)
            continue
        future_high = highs[i + 1:i + 1 + forward_window].max()
        future_low = lows[i + 1:i + 1 + forward_window].min()
        excursion = (future_high - future_low) / atr_series.iloc[i]
        labels.append(1 if excursion < range_threshold_atr else 0)  # 1 = ranging

    return pd.Series(labels, index=df.index)


def build_dataset(lookback_bars: int, forward_window: int) -> tuple[pd.DataFrame, pd.Series]:
    df_h1 = data_feed.get_h1(outputsize=lookback_bars)

    rows = []
    for i in range(60, len(df_h1)):
        window = df_h1.iloc[:i + 1]
        rows.append({
            "adx": float(indicators.adx(window).iloc[-1]),
            "atr_pctile": indicators.atr_percentile(window),
            "bb_width_pctile": indicators.bollinger_band_width_percentile(window),
            "choppiness": float(indicators.choppiness_index(window).iloc[-1]),
        })
    features_df = pd.DataFrame(rows, index=df_h1.index[60:])

    labels = label_regime(df_h1, forward_window).iloc[60:]

    combined = features_df.join(labels.rename("label")).dropna()
    return combined.drop(columns=["label"]), combined["label"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback_bars", type=int, default=5000)
    parser.add_argument("--forward_window", type=int, default=12)
    args = parser.parse_args()

    X, y = build_dataset(args.lookback_bars, args.forward_window)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print(classification_report(y_test, preds, target_names=["trending", "ranging"]))

    model.save_model("app/model.json")
    print("Saved model.json")


if __name__ == "__main__":
    main()
