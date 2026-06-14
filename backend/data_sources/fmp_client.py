from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import urllib.parse
import urllib.request
from typing import Any

from models import CompanyMetrics


FMP_BASE_URL = "https://financialmodelingprep.com/stable"


def enrich_with_fmp(metrics: CompanyMetrics, api_key: str) -> CompanyMetrics:
    symbol = metrics.ticker
    year, quarter = _latest_completed_quarter()
    endpoints = {
        "profile": ("profile", {"symbol": symbol}),
        "quote": ("quote", {"symbol": symbol}),
        "ratios": ("ratios-ttm", {"symbol": symbol}),
        "shares_float": ("shares-float", {"symbol": symbol}),
        "insider_trades": ("insider-trading/search", {"symbol": symbol, "page": 0, "limit": 100}),
        "institutional": (
            "institutional-ownership/extract-analytics/holder",
            {"symbol": symbol, "year": year, "quarter": quarter, "page": 0, "limit": 20},
        ),
    }

    with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        futures = {
            name: executor.submit(_get, path, params, api_key)
            for name, (path, params) in endpoints.items()
        }
        responses = {name: future.result() for name, future in futures.items()}

    profile = _first(responses["profile"])
    quote = _first(responses["quote"])
    ratios = _first(responses["ratios"])
    shares_float = _first(responses["shares_float"])
    insider_trades = _records(responses["insider_trades"])
    institutional = _records(responses["institutional"])

    metrics.sec_cik = metrics.sec_cik or _normalized_cik(_text(profile, "cik"))
    metrics.company_name = metrics.company_name or _text(profile, "companyName", "name")
    metrics.sector = metrics.sector or _text(profile, "sector")
    metrics.industry = metrics.industry or _text(profile, "industry")
    metrics.business_summary = metrics.business_summary or _text(profile, "description")
    metrics.market_cap = metrics.market_cap or _number(quote, "marketCap") or _number(profile, "marketCap")
    metrics.beta = metrics.beta or _number(profile, "beta", "beta1Year")
    metrics.average_volume = metrics.average_volume or _number(quote, "avgVolume", "volume")
    reported_shares = _number(shares_float, "outstandingShares", "sharesOutstanding") or _number(
        quote, "sharesOutstanding"
    )
    if reported_shares is not None and metrics.shares_outstanding_source != "Yahoo reported shares outstanding":
        metrics.shares_outstanding = reported_shares
        metrics.shares_outstanding_source = "FMP reported shares outstanding"
    fmp_pe = _number(quote, "pe", "priceEarningsRatio")
    if fmp_pe is not None and (
        metrics.trailing_pe is None or (metrics.trailing_pe_source or "").startswith("Derived")
    ):
        metrics.trailing_pe = fmp_pe
        metrics.trailing_pe_source = "FMP reported trailing P/E"
    fmp_profit_margin = _number(ratios, "netProfitMarginTTM", "netProfitMargin")
    if fmp_profit_margin is not None and (
        metrics.profit_margin is None or (metrics.profit_margin_source or "").startswith("Derived")
    ):
        metrics.profit_margin = fmp_profit_margin
        metrics.profit_margin_source = "FMP reported TTM net profit margin"
    fmp_operating_margin = _number(ratios, "operatingProfitMarginTTM", "operatingProfitMargin")
    if fmp_operating_margin is not None and (
        metrics.operating_margin is None or (metrics.operating_margin_source or "").startswith("Derived")
    ):
        metrics.operating_margin = fmp_operating_margin
        metrics.operating_margin_source = "FMP reported TTM operating profit margin"
    fmp_debt_to_equity = _number(
        ratios, "debtEquityRatioTTM", "debtToEquityRatioTTM", "debtEquityRatio"
    )
    if fmp_debt_to_equity is not None and (
        metrics.debt_to_equity is None or (metrics.debt_to_equity_source or "").startswith("Derived")
    ):
        metrics.debt_to_equity = fmp_debt_to_equity
        metrics.debt_to_equity_source = "FMP reported debt-to-equity ratio"
    metrics.dividend_yield = metrics.dividend_yield or _number(ratios, "dividendYieldTTM", "dividendYield")

    purchases, trades_available = _recent_insider_purchases(insider_trades, responses["insider_trades"].available)
    if not metrics.recent_insider_purchases_available and trades_available:
        metrics.recent_insider_purchases = purchases
        metrics.recent_insider_purchases_available = True

    if metrics.insider_ownership is None:
        ownership = _estimated_insider_ownership(insider_trades, metrics.shares_outstanding)
        if ownership is not None:
            metrics.insider_ownership = ownership
            metrics.insider_ownership_source = "Estimated from latest FMP Form 4 reported holdings / shares outstanding"

    holders, holders_available = _institutional_holders(institutional, responses["institutional"].available)
    if not metrics.institutional_holders_available and holders_available:
        metrics.institutional_holders = holders
        metrics.institutional_holders_available = True

    successful = [name for name, response in responses.items() if response.available]
    if successful:
        metrics.source_notes.append("FMP supplement used: " + ", ".join(successful) + ".")
    else:
        metrics.source_notes.append(
            "FMP_API_KEY is configured, but no requested FMP datasets were available for this ticker or plan."
        )
    return metrics


class FMPResponse:
    def __init__(self, data: Any = None, available: bool = False):
        self.data = data
        self.available = available


def _get(path: str, params: dict[str, Any], api_key: str) -> FMPResponse:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{FMP_BASE_URL}/{path}?{query}",
        headers={"Accept": "application/json", "apikey": api_key, "User-Agent": "stock-screening-tool/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        if isinstance(data, dict) and any(key in data for key in ("Error Message", "error", "message")):
            return FMPResponse()
        return FMPResponse(data, True)
    except Exception:
        return FMPResponse()


def _first(response: FMPResponse) -> dict[str, Any]:
    records = _records(response)
    return records[0] if records else {}


def _records(response: FMPResponse) -> list[dict[str, Any]]:
    data = response.data
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _recent_insider_purchases(records: list[dict[str, Any]], available: bool) -> tuple[list[dict[str, Any]], bool]:
    if not available:
        return [], False
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=180)
    purchases = []
    for item in records:
        acquisition = _text(item, "acquisitionOrDisposition")
        transaction_type = (_text(item, "transactionType", "transactionCode") or "").lower()
        if acquisition != "A" and "purchase" not in transaction_type and transaction_type != "p":
            continue
        date = _date(item, "transactionDate", "filingDate")
        if date is None or date < cutoff:
            continue
        shares = _number(item, "securitiesTransacted", "transactionShares")
        price = _number(item, "price", "transactionPrice")
        purchases.append(
            {
                "date": date.isoformat(),
                "insider": _text(item, "reportingName", "name") or "Unknown",
                "position": _text(item, "typeOfOwner", "officerTitle") or "Unknown",
                "shares": shares,
                "value": shares * price if shares is not None and price is not None else None,
            }
        )
    return purchases, True


def _estimated_insider_ownership(records: list[dict[str, Any]], shares_outstanding: float | None) -> float | None:
    if not records or not shares_outstanding or shares_outstanding <= 0:
        return None
    latest_holdings: dict[str, float] = {}
    for item in records:
        security = (_text(item, "securityName") or "").lower()
        if security and "stock" not in security and "share" not in security:
            continue
        owner = _text(item, "reportingCik", "reportingName")
        owned = _number(item, "securitiesOwned", "securitiesOwnedFollowingTransaction")
        if owner and owned is not None and owner not in latest_holdings:
            latest_holdings[owner] = owned
    if not latest_holdings:
        return None
    return min(sum(latest_holdings.values()) / shares_outstanding, 1.0)


def _institutional_holders(records: list[dict[str, Any]], available: bool) -> tuple[list[dict[str, Any]], bool]:
    if not available:
        return [], False
    holders = []
    for item in records:
        percent = _number(item, "portfolioWeight", "ownershipPercent", "percentHeld")
        if percent is not None and percent > 1:
            percent /= 100
        if percent is None or percent < 0.01:
            continue
        holders.append(
            {
                "holder": _text(item, "investorName", "holder", "name") or "Unknown",
                "percent_held": percent,
                "shares": _number(item, "shares", "sharesNumber"),
                "value": _number(item, "marketValue", "value"),
            }
        )
    return holders, True


def _latest_completed_quarter() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    quarter = (now.month - 1) // 3
    if quarter == 0:
        return now.year - 1, 4
    return now.year, quarter


def _text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _number(item: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        try:
            value = item.get(key)
            if value is None:
                continue
            number = float(value)
            if math.isfinite(number):
                return number
        except (TypeError, ValueError):
            continue
    return None


def _date(item: dict[str, Any], *keys: str):
    for key in keys:
        value = item.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def _normalized_cik(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    return digits.zfill(10) if digits else None
