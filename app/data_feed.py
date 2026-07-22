"""
Twelve Data feed wrapper — mirrors the pattern used in AURUM / GAIA.
Pulls H1 and H4 OHLCV for XAU/USD. Single call per timeframe per signal
cycle to conserve API credits (lesson learned from TITAN's credit exhaustion).
"""
import os
import requests
import pandas as pd

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com/time_series"
SYMBOL = "XAU/USD"


def _fetch(interval: str, outputsize: int = 150) -> pd.DataFrame:
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }
    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Twelve Data error for {interval}: {data}")

    df = pd.DataFrame(data["values"])
    df = df.rename(columns={"datetime": "time"})
    df["time"] = pd.to_datetime(df["time"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def get_h1(outputsize: int = 150) -> pd.DataFrame:
    return _fetch("1h", outputsize)


def get_h4(outputsize: int = 100) -> pd.DataFrame:
    return _fetch("4h", outputsize)
