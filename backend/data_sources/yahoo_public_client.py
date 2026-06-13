from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Any

from models import CompanyMetrics


YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"


def fetch_with_yahoo_public(ticker: str) -> CompanyMetrics:
    symbol = ticker.upper().strip()
    params = urllib.parse.urlencode({"symbols": symbol})
    request = urllib.request.Request(
        f"{YAHOO_QUOTE_URL}?{params}",
        headers={
            "User-Agent": "Mozilla/5.0 stock-screening-tool/0.1",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))

    results = payload.get("quoteResponse", {}).get("result", [])
    if not results:
        raise ValueError(f"No quote data returned for {symbol}")
    item = results[0]

    return CompanyMetrics(
        ticker=symbol,
        company_name=item.get("longName") or item.get("shortName"),
        sector=item.get("sector"),
        industry=item.get("industry"),
        market_cap=_num(item.get("marketCap")),
        trailing_pe=_num(item.get("trailingPE")),
        forward_pe=_num(item.get("forwardPE")),
        beta=_num(item.get("beta")),
        dividend_yield=_yield_decimal(item.get("trailingAnnualDividendYield")),
        average_volume=_num(item.get("averageDailyVolume3Month") or item.get("averageDailyVolume10Day")),
        shares_outstanding=_num(item.get("sharesOutstanding")),
        source_notes=[
            "Primary source: Yahoo Finance public quote endpoint",
            "Install yfinance for richer financial statements and more complete scoring.",
        ],
        raw={},
    )


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def _yield_decimal(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if number > 0.2:
        return number / 100
    return number
