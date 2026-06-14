from __future__ import annotations

from models import CompanyMetrics

from .yahoo_public_client import fetch_with_yahoo_public
from .yfinance_client import YFinanceUnavailable, fetch_with_yfinance


def fetch_company_metrics(ticker: str) -> CompanyMetrics:
    symbol = ticker.upper().strip()
    if not symbol:
        raise ValueError("Ticker is required")

    try:
        return fetch_with_yfinance(symbol)
    except YFinanceUnavailable:
        primary_error = "yfinance is not installed"
    except Exception as exc:
        primary_error = str(exc)

    try:
        fallback = fetch_with_yahoo_public(symbol)
        fallback.source_notes.append(f"yfinance failed; used Yahoo public fallback instead: {primary_error}")
        return fallback
    except Exception as fallback_exc:
        return CompanyMetrics(
            ticker=symbol,
            source_notes=[
                "Live market data is temporarily unavailable.",
                f"yfinance error: {primary_error}",
                f"Yahoo quote fallback error: {fallback_exc}",
            ],
        )
