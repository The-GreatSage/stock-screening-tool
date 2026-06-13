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
        return fetch_with_yahoo_public(symbol)
    except Exception as exc:
        fallback = fetch_with_yahoo_public(symbol)
        fallback.source_notes.append(f"yfinance failed; used Yahoo public fallback instead: {exc}")
        return fallback
