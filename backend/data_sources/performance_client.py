from __future__ import annotations

from datetime import datetime, timezone
import math
from threading import Lock
from time import monotonic
from typing import Any


PERFORMANCE_CACHE_SECONDS = 15 * 60
_performance_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_performance_cache_lock = Lock()

BENCHMARK_GROUPS = {
    "mining": [("XME", "Metals & Mining"), ("GDX", "Gold Miners")],
    "semiconductors": [("SOXX", "Semiconductors"), ("QQQ", "Nasdaq 100")],
    "technology": [("QQQ", "Nasdaq 100"), ("SPY", "S&P 500")],
    "energy": [("XLE", "Energy"), ("OIH", "Oil Services")],
    "healthcare": [("XLV", "Health Care"), ("XBI", "Biotechnology")],
    "financials": [("XLF", "Financials"), ("KRE", "Regional Banks")],
    "consumer_cyclical": [("XLY", "Consumer Discretionary"), ("SPY", "S&P 500")],
    "consumer_defensive": [("XLP", "Consumer Staples"), ("SPY", "S&P 500")],
    "industrials": [("XLI", "Industrials"), ("SPY", "S&P 500")],
    "utilities": [("XLU", "Utilities"), ("SPY", "S&P 500")],
    "real_estate": [("XLRE", "Real Estate"), ("SPY", "S&P 500")],
    "communication": [("XLC", "Communication Services"), ("QQQ", "Nasdaq 100")],
    "materials": [("XLB", "Materials"), ("SPY", "S&P 500")],
    "default": [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100")],
}


def fetch_relative_performance(ticker: str, sector: str = "", industry: str = "") -> dict[str, Any]:
    symbol = ticker.upper().strip()
    benchmarks, rationale = select_benchmarks(sector, industry)
    cache_key = (symbol, *[benchmark[0] for benchmark in benchmarks])
    now = monotonic()
    with _performance_cache_lock:
        cached = _performance_cache.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1]

    try:
        import yfinance as yf
    except ModuleNotFoundError:
        return _empty_payload(symbol, benchmarks, rationale)

    labels = [(symbol, symbol), *benchmarks]
    try:
        frame = yf.download(
            [item[0] for item in labels],
            period="1y",
            interval="1d",
            progress=False,
            threads=True,
            auto_adjust=True,
        )
    except Exception:
        return _empty_payload(symbol, benchmarks, rationale)

    series = []
    for series_symbol, name in labels:
        points = _series_from_frame(frame, series_symbol, len(labels))
        if not points:
            points = _download_single_series(yf, series_symbol)
        if points:
            series.append({"symbol": series_symbol, "name": name, "points": points})

    payload = {
        "ticker": symbol,
        "benchmarks": [{"symbol": item[0], "name": item[1]} for item in benchmarks],
        "rationale": rationale,
        "series": series,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if any(item["symbol"] == symbol for item in series):
        with _performance_cache_lock:
            _performance_cache[cache_key] = (monotonic() + PERFORMANCE_CACHE_SECONDS, payload)
    return payload


def select_benchmarks(sector: str = "", industry: str = "") -> tuple[list[tuple[str, str]], str]:
    sector_text = (sector or "").lower()
    industry_text = (industry or "").lower()
    combined = f"{sector_text} {industry_text}"

    if any(word in combined for word in ("mining", "gold", "silver", "copper", "metal", "coal")):
        return BENCHMARK_GROUPS["mining"], "Mining and metals industry benchmarks"
    if any(word in combined for word in ("semiconductor", "chip")):
        return BENCHMARK_GROUPS["semiconductors"], "Semiconductor industry and Nasdaq benchmarks"
    if any(word in combined for word in ("oil", "gas", "energy", "petroleum", "uranium")):
        return BENCHMARK_GROUPS["energy"], "Energy industry benchmarks"
    if any(word in combined for word in ("biotech", "pharma", "drug", "medical", "health")):
        return BENCHMARK_GROUPS["healthcare"], "Health care and biotechnology benchmarks"
    if any(word in combined for word in ("bank", "insurance", "financial", "capital market", "asset management")):
        return BENCHMARK_GROUPS["financials"], "Financial industry benchmarks"
    if any(word in combined for word in ("software", "technology", "computer", "internet", "electronics")):
        return BENCHMARK_GROUPS["technology"], "Technology-oriented Nasdaq and broad-market benchmarks"

    sector_map = {
        "technology": "technology",
        "financial services": "financials",
        "financials": "financials",
        "healthcare": "healthcare",
        "energy": "energy",
        "consumer cyclical": "consumer_cyclical",
        "consumer defensive": "consumer_defensive",
        "industrials": "industrials",
        "utilities": "utilities",
        "real estate": "real_estate",
        "communication services": "communication",
        "basic materials": "materials",
    }
    group = sector_map.get(sector_text, "default")
    rationale = f"{sector or 'Broad market'} sector benchmarks"
    return BENCHMARK_GROUPS[group], rationale


def _series_from_frame(frame: Any, symbol: str, symbol_count: int) -> list[dict[str, Any]]:
    try:
        closes = frame["Close"][symbol] if symbol_count > 1 else frame["Close"]
        dates = list(closes.index)
        values = closes.tolist()
    except Exception:
        return []
    return _normalize_points(dates, values)


def _download_single_series(yf: Any, symbol: str) -> list[dict[str, Any]]:
    try:
        frame = yf.download(
            symbol,
            period="1y",
            interval="1d",
            progress=False,
            threads=False,
            auto_adjust=True,
        )
    except Exception:
        return []
    return _series_from_frame(frame, symbol, 1)


def _normalize_points(dates: list[Any], values: list[Any]) -> list[dict[str, Any]]:
    valid = []
    for date, value in zip(dates, values):
        number = _number(value)
        if number is None:
            continue
        valid.append((_iso_date(date), number))
    if not valid or valid[0][1] == 0:
        return []
    baseline = valid[0][1]
    return [
        {"date": date, "value": ((value / baseline) - 1) * 100}
        for date, value in valid
    ]


def _empty_payload(symbol: str, benchmarks: list[tuple[str, str]], rationale: str) -> dict[str, Any]:
    return {
        "ticker": symbol,
        "benchmarks": [{"symbol": item[0], "name": item[1]} for item in benchmarks],
        "rationale": rationale,
        "series": [],
        "generated_at": None,
    }


def _iso_date(value: Any) -> str:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
