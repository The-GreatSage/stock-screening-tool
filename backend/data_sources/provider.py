from __future__ import annotations

from copy import deepcopy
import os
from threading import Lock
from time import monotonic

from models import CompanyMetrics

from .fmp_client import enrich_with_fmp
from .sec_client import enrich_with_sec
from .yahoo_public_client import fetch_with_yahoo_public
from .yfinance_client import YFinanceUnavailable, fetch_with_yfinance

CACHE_TTL_SECONDS = 15 * 60
_cache: dict[str, tuple[float, CompanyMetrics]] = {}
_cache_lock = Lock()


def fetch_company_metrics(ticker: str) -> CompanyMetrics:
    symbol = ticker.upper().strip()
    if not symbol:
        raise ValueError("Ticker is required")

    cached = _get_cached(symbol)
    if cached is not None:
        response = deepcopy(cached)
        response.source_notes = [*response.source_notes, "Served from 15-minute cache."]
        return response

    try:
        metrics = fetch_with_yfinance(symbol)
        metrics = _supplement_with_fmp(metrics)
        metrics = _supplement_with_sec(metrics)
        _set_cached(symbol, metrics)
        return deepcopy(metrics)
    except YFinanceUnavailable:
        primary_error = "yfinance is not installed"
    except Exception as exc:
        primary_error = str(exc)

    try:
        fallback = fetch_with_yahoo_public(symbol)
        fallback.source_notes.append(f"yfinance failed; used Yahoo public fallback instead: {primary_error}")
        fallback = _supplement_with_fmp(fallback)
        fallback = _supplement_with_sec(fallback)
        _set_cached(symbol, fallback)
        return fallback
    except Exception as fallback_exc:
        metrics = CompanyMetrics(
            ticker=symbol,
            source_notes=[
                "Live market data is temporarily unavailable.",
                f"yfinance error: {primary_error}",
                f"Yahoo quote fallback error: {fallback_exc}",
            ],
        )
        _set_cached(symbol, metrics, ttl_seconds=60)
        return metrics


def _get_cached(symbol: str) -> CompanyMetrics | None:
    with _cache_lock:
        cached = _cache.get(symbol)
        if cached is None:
            return None
        expires_at, metrics = cached
        if expires_at <= monotonic():
            _cache.pop(symbol, None)
            return None
        return metrics


def _set_cached(symbol: str, metrics: CompanyMetrics, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
    with _cache_lock:
        _cache[symbol] = (monotonic() + ttl_seconds, metrics)


def _supplement_with_fmp(metrics: CompanyMetrics) -> CompanyMetrics:
    api_key = _fmp_api_key()
    if not api_key:
        return metrics
    try:
        return enrich_with_fmp(metrics, api_key)
    except Exception as exc:
        metrics.source_notes.append(f"FMP supplement unavailable: {exc}")
        return metrics


def _fmp_api_key() -> str:
    return os.environ.get("FMP_API_KEY", "").strip() or os.environ.get("FMP_API", "").strip()


def _supplement_with_sec(metrics: CompanyMetrics) -> CompanyMetrics:
    user_agent = _sec_user_agent()
    if not user_agent:
        return metrics
    try:
        return enrich_with_sec(metrics, user_agent)
    except Exception as exc:
        metrics.source_notes.append(f"SEC EDGAR supplement unavailable: {exc}")
        return metrics


def _sec_user_agent() -> str:
    value = os.environ.get("SEC_USER_AGENT", "").strip()
    if value and "@" in value and " " not in value:
        return f"StockScreeningTool/1.0 {value}"
    return value
