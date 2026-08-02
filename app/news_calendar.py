"""
News blackout logic for AURUM_GRID.

Uses the public Forex Factory weekly calendar JSON feed (no API key required).
Caches results for an hour so we're not re-fetching on every /grid_signal call.

Blocks grid deployment around HIGH-impact USD events (NFP, CPI, FOMC, etc.)
since gold is extremely USD-data-sensitive and grids handle gaps poorly.
"""
import requests
from datetime import datetime, timezone, timedelta

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BLACKOUT_BEFORE_MINUTES = 30
BLACKOUT_AFTER_MINUTES = 30
RELEVANT_CURRENCIES = {"USD"}

_cache = {"events": None, "fetched_at": None}
CACHE_TTL_SECONDS = 3600


def _fetch_calendar() -> list:
    now = datetime.now(timezone.utc)
    if _cache["events"] is not None and _cache["fetched_at"] is not None:
        age = (now - _cache["fetched_at"]).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return _cache["events"]

    try:
        resp = requests.get(CALENDAR_URL, timeout=10)
        resp.raise_for_status()
        events = resp.json()
        _cache["events"] = events
        _cache["fetched_at"] = now
        return events
    except Exception as e:
        print(f"News calendar fetch failed: {e}")
        return _cache["events"] or []


def _parse_event_time(event: dict):
    try:
        return datetime.fromisoformat(event["date"]).astimezone(timezone.utc)
    except Exception:
        return None


def is_blackout(now: datetime = None) -> bool:
    if now is None:
        now = datetime.now(timezone.utc)

    events = _fetch_calendar()
    for event in events:
        if event.get("country") not in RELEVANT_CURRENCIES:
            continue
        if event.get("impact") != "High":
            continue

        event_time = _parse_event_time(event)
        if event_time is None:
            continue

        window_start = event_time - timedelta(minutes=BLACKOUT_BEFORE_MINUTES)
        window_end = event_time + timedelta(minutes=BLACKOUT_AFTER_MINUTES)

        if window_start <= now <= window_end:
            return True

    return False
