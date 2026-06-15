from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import math
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

    available_symbols = {market["symbol"] for market in markets}
    missing_markets = [
        (symbol, name)
        for symbol, name in MARKETS
        if symbol not in available_symbols
    ]
    if missing_markets:
        markets.extend(_fetch_market_history(yf, missing_markets))
    markets.sort(key=lambda market: [symbol for symbol, _ in MARKETS].index(market["symbol"]))

    payload = {
        "markets": markets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if markets:
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


def _fetch_market_history(yf: Any, markets: list[tuple[str, str]]) -> list[dict[str, Any]]:
    symbols = [symbol for symbol, _ in markets]
    try:
        frame = yf.download(
            symbols,
            period="5d",
            interval="1d",
            progress=False,
            threads=True,
            auto_adjust=False,
        )
    except Exception:
        return []
    quotes = []
    for symbol, name in markets:
        try:
            closes = frame["Close"][symbol] if len(symbols) > 1 else frame["Close"]
            quote = _quote_from_closes(symbol, name, closes.tolist())
            if quote is not None:
                quotes.append(quote)
        except Exception:
            continue
    return quotes


def _quote_from_closes(symbol: str, name: str, closes: list[Any]) -> dict[str, Any] | None:
    values = [number for value in closes if (number := _number(value)) is not None]
    if not values:
        return None
    price = values[-1]
    previous_close = values[-2] if len(values) >= 2 else None
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
        number = float(value) if value is not None else None
        return number if number is not None and math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
