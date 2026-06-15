from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any


MARKETS = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow Jones"),
    ("^RUT", "Russell 2000"),
    ("^VIX", "VIX"),
    ("GC=F", "Gold"),
    ("CL=F", "Crude Oil"),
    ("BTC-USD", "Bitcoin"),
]
MARKET_CACHE_SECONDS = 5 * 60
_market_cache: tuple[float, dict[str, Any]] | None = None
_market_cache_lock = Lock()


def fetch_market_overview() -> dict[str, Any]:
    global _market_cache
    now = monotonic()
    with _market_cache_lock:
        if _market_cache is not None and _market_cache[0] > now:
            return _market_cache[1]

    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return {"markets": [], "generated_at": None}

    with ThreadPoolExecutor(max_workers=len(MARKETS)) as executor:
        futures = [
            executor.submit(_fetch_market, yf, symbol, name)
            for symbol, name in MARKETS
        ]
        markets = [quote for future in futures if (quote := future.result()) is not None]

    payload = {
        "markets": markets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _market_cache_lock:
        _market_cache = (monotonic() + MARKET_CACHE_SECONDS, payload)
    return payload


def _fetch_market(yf: Any, symbol: str, name: str) -> dict[str, Any] | None:
    try:
        fast_info = dict(yf.Ticker(symbol).fast_info)
    except Exception:
        return None
    price = _number(fast_info.get("lastPrice"))
    previous_close = _number(fast_info.get("previousClose"))
    if price is None:
        return None
    change = price - previous_close if previous_close is not None else None
    change_percent = change / previous_close if change is not None and previous_close else None
    return {
        "symbol": symbol,
        "name": name,
        "price": price,
        "change": change,
        "change_percent": change_percent,
    }


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
