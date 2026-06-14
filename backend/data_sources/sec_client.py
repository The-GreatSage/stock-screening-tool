from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from threading import Lock
from time import monotonic, sleep
from typing import Any
import urllib.request
import xml.etree.ElementTree as ET

from models import CompanyMetrics


SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
TICKER_CACHE_SECONDS = 24 * 60 * 60
MAX_OWNERSHIP_FILINGS = 24

_ticker_cache: tuple[float, dict[str, str]] | None = None
_ticker_lock = Lock()


def enrich_with_sec(metrics: CompanyMetrics, user_agent: str) -> CompanyMetrics:
    if metrics.insider_ownership is not None and metrics.recent_insider_purchases_available:
        return metrics

    cik = metrics.sec_cik or _ticker_to_cik(metrics.ticker, user_agent)
    if cik is None:
        metrics.source_notes.append("SEC EDGAR could not map this ticker to a CIK.")
        return metrics

    submissions = _get_json(SEC_SUBMISSIONS_URL.format(cik=cik), user_agent)
    filings = _ownership_filings(submissions, cik)
    if not filings:
        metrics.source_notes.append("SEC EDGAR returned no recent Forms 3, 4, or 5 for this company.")
        metrics.recent_insider_purchases_available = True
        return metrics

    purchases: list[dict[str, Any]] = []
    latest_holdings: dict[str, float] = {}
    successful_filings = 0
    for filing in filings:
        try:
            xml = _get_bytes(filing["url"], user_agent)
            parsed = parse_ownership_xml(xml)
            successful_filings += 1
        except Exception:
            continue

        owner_key = parsed["owner_cik"] or parsed["owner_name"]
        if owner_key and parsed["shares_owned"] is not None and owner_key not in latest_holdings:
            latest_holdings[owner_key] = parsed["shares_owned"]
        purchases.extend(parsed["purchases"])

    if successful_filings == 0:
        metrics.source_notes.append("SEC EDGAR ownership filings were listed but could not be downloaded.")
        return metrics

    metrics.recent_insider_purchases = purchases
    metrics.recent_insider_purchases_available = True

    if metrics.insider_ownership is None and metrics.shares_outstanding and latest_holdings:
        metrics.insider_ownership = min(sum(latest_holdings.values()) / metrics.shares_outstanding, 1.0)
        metrics.insider_ownership_source = (
            "Estimated from each insider's latest available SEC Form 3/4/5 reported common-share holdings "
            "divided by shares outstanding; may be incomplete or include indirect holdings."
        )

    metrics.source_notes.append(
        f"SEC EDGAR supplement used: parsed {successful_filings} recent ownership filing(s)."
    )
    return metrics


def parse_ownership_xml(xml: bytes) -> dict[str, Any]:
    root = ET.fromstring(xml)
    _remove_namespaces(root)
    owner_name = _find_text(root, ".//reportingOwnerId/rptOwnerName")
    owner_cik = _find_text(root, ".//reportingOwnerId/rptOwnerCik")
    position = _owner_position(root)
    purchases = []
    latest_shares = None
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=180)

    for transaction in root.findall(".//nonDerivativeTransaction"):
        code = _find_text(transaction, ".//transactionCoding/transactionCode")
        acquired = _find_text(transaction, ".//transactionAmounts/transactionAcquiredDisposedCode/value")
        date = _parse_date(_find_text(transaction, ".//transactionDate/value"))
        shares = _number(_find_text(transaction, ".//transactionAmounts/transactionShares/value"))
        price = _number(_find_text(transaction, ".//transactionAmounts/transactionPricePerShare/value"))
        shares_owned = _number(
            _find_text(transaction, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value")
        )
        if shares_owned is not None:
            latest_shares = shares_owned
        if code != "P" or acquired != "A" or date is None or date < cutoff:
            continue
        purchases.append(
            {
                "date": date.isoformat(),
                "insider": owner_name or "Unknown",
                "position": position,
                "shares": shares,
                "value": shares * price if shares is not None and price is not None else None,
            }
        )

    if latest_shares is None:
        holdings = [
            _number(_find_text(holding, ".//postTransactionAmounts/sharesOwnedFollowingTransaction/value"))
            or _number(_find_text(holding, ".//sharesOwnedFollowingTransaction/value"))
            for holding in root.findall(".//nonDerivativeHolding")
        ]
        latest_shares = sum(value for value in holdings if value is not None) if any(
            value is not None for value in holdings
        ) else None

    return {
        "owner_name": owner_name,
        "owner_cik": owner_cik,
        "shares_owned": latest_shares,
        "purchases": purchases,
    }


def _ownership_filings(submissions: dict[str, Any], cik: str) -> list[dict[str, str]]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
    filings = []
    for form, accession, document, filing_date in zip(forms, accessions, documents, filing_dates):
        if form not in {"3", "4", "5", "3/A", "4/A", "5/A"}:
            continue
        date = _parse_date(filing_date)
        if date is None or date < cutoff or not accession or not document:
            continue
        filings.append(
            {
                "url": SEC_ARCHIVES_URL.format(
                    cik=str(int(cik)),
                    accession=accession.replace("-", ""),
                    document=document,
                )
            }
        )
        if len(filings) >= MAX_OWNERSHIP_FILINGS:
            break
    return filings


def _ticker_to_cik(ticker: str, user_agent: str) -> str | None:
    global _ticker_cache
    now = monotonic()
    with _ticker_lock:
        if _ticker_cache is None or _ticker_cache[0] <= now:
            payload = _get_json(SEC_TICKERS_URL, user_agent)
            mapping = {
                str(item.get("ticker", "")).upper(): str(item.get("cik_str", "")).zfill(10)
                for item in payload.values()
                if isinstance(item, dict) and item.get("ticker") and item.get("cik_str")
            }
            _ticker_cache = (now + TICKER_CACHE_SECONDS, mapping)
        return _ticker_cache[1].get(ticker.upper())


def _get_json(url: str, user_agent: str) -> dict[str, Any]:
    return json.loads(_get_bytes(url, user_agent).decode("utf-8"))


def _get_bytes(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/xml, text/xml",
            "User-Agent": user_agent,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        data = response.read()
    sleep(0.12)
    return data


def _owner_position(root: ET.Element) -> str:
    relationship = root.find(".//reportingOwnerRelationship")
    if relationship is None:
        return "Unknown"
    officer_title = _find_text(relationship, ".//officerTitle")
    if officer_title:
        return officer_title
    roles = []
    for tag, label in (("isDirector", "Director"), ("isOfficer", "Officer"), ("isTenPercentOwner", "10% Owner")):
        if _find_text(relationship, f".//{tag}") == "1":
            roles.append(label)
    return ", ".join(roles) or "Other"


def _remove_namespaces(root: ET.Element) -> None:
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]


def _find_text(root: ET.Element, path: str) -> str | None:
    element = root.find(path)
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _number(value: str | None) -> float | None:
    try:
        if value is None:
            return None
        number = float(value.replace(",", ""))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None
