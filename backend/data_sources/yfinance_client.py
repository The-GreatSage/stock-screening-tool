from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from models import CompanyMetrics


class YFinanceUnavailable(RuntimeError):
    pass


def fetch_with_yfinance(ticker: str) -> CompanyMetrics:
    try:
        import yfinance as yf
    except ModuleNotFoundError as exc:
        raise YFinanceUnavailable("yfinance is not installed") from exc

    symbol = ticker.upper().strip()
    stock = yf.Ticker(symbol)
    info = stock.info or {}
    financials = _safe_frame_dict(getattr(stock, "financials", None))
    quarterly_financials = _safe_frame_dict(getattr(stock, "quarterly_financials", None))
    balance_sheet = _safe_frame_dict(getattr(stock, "balance_sheet", None))
    cashflow = _safe_frame_dict(getattr(stock, "cashflow", None))
    recent_insider_purchases = _recent_insider_purchases(_safe_property(stock, "insider_transactions"))
    institutional_holders = _institutional_holders(_safe_property(stock, "institutional_holders"))

    revenue_history = _row_values(financials, "Total Revenue")
    earnings_history = _row_values(financials, "Net Income")
    margin_history = _margin_history(revenue_history, earnings_history)
    shares_history = _row_values(financials, "Diluted Average Shares") or _row_values(financials, "Basic Average Shares")
    share_repurchase_history = _row_values(cashflow, "Repurchase Of Capital Stock")

    quarterly_earnings = _latest(_row_values(quarterly_financials, "Net Income"))
    annual_earnings = _latest(earnings_history)

    roic, roic_details = _calculate_roic(financials, balance_sheet)

    metrics = CompanyMetrics(
        ticker=symbol,
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        business_summary=info.get("longBusinessSummary"),
        market_cap=_num(info.get("marketCap")),
        trailing_pe=_num(info.get("trailingPE")),
        forward_pe=_num(info.get("forwardPE")),
        peg_ratio=_num(info.get("pegRatio") or info.get("trailingPegRatio")),
        beta=_num(info.get("beta")),
        profit_margin=_num(info.get("profitMargins")),
        operating_margin=_num(info.get("operatingMargins")),
        return_on_invested_capital=roic,
        roic_details=roic_details,
        total_cash=_num(info.get("totalCash")),
        total_debt=_num(info.get("totalDebt")),
        debt_to_equity=_num(info.get("debtToEquity")),
        quarterly_earnings=quarterly_earnings,
        annual_earnings=annual_earnings,
        revenue_history=list(reversed(revenue_history)),
        earnings_history=list(reversed(earnings_history)),
        margin_history=list(reversed(margin_history)),
        average_volume=_num(info.get("averageVolume") or info.get("averageDailyVolume10Day")),
        shares_outstanding=_num(info.get("sharesOutstanding")),
        shares_history=list(reversed(shares_history)),
        share_repurchase_history=list(reversed(share_repurchase_history)),
        insider_ownership=_num(info.get("heldPercentInsiders")),
        dividend_yield=_yield_decimal(info.get("dividendYield")),
        recent_insider_purchases=recent_insider_purchases,
        institutional_holders=institutional_holders,
        source_notes=["Primary source: yfinance"],
        raw={},
    )
    return metrics


def _safe_frame_dict(frame: Any) -> dict[str, list[float]]:
    if frame is None:
        return {}
    try:
        if frame.empty:
            return {}
        return {
            str(index): [_num(value) for value in frame.loc[index].tolist()]
            for index in frame.index
        }
    except Exception:
        return {}


def _safe_property(stock: Any, name: str) -> Any:
    try:
        return getattr(stock, name, None)
    except Exception:
        return None


def _row_values(data: dict[str, list[float]], name: str) -> list[float]:
    return [value for value in data.get(name, []) if value is not None]


def _latest(values: list[float]) -> float | None:
    if not values:
        return None
    return values[0]


def _margin_history(revenue: list[float], earnings: list[float]) -> list[float]:
    margins = []
    for rev, earn in zip(revenue, earnings):
        if rev:
            margins.append(earn / rev)
    return margins


def _effective_tax_rate(financials: dict[str, list[float]]) -> tuple[float, str]:
    pretax = _latest(_row_values(financials, "Pretax Income"))
    tax = _latest(_row_values(financials, "Tax Provision"))
    if pretax and tax is not None and pretax > 0:
        rate = tax / pretax
        if 0 <= rate <= 0.5:
            return rate, "effective tax rate from Tax Provision / Pretax Income"
    return 0.21, "21% statutory fallback because effective tax rate was unavailable or abnormal"


def _calculate_roic(
    financials: dict[str, list[float]],
    balance_sheet: dict[str, list[float]],
) -> tuple[float | None, dict[str, Any]]:
    operating_income = _latest(_row_values(financials, "Operating Income"))
    tax_rate, tax_rate_source = _effective_tax_rate(financials)
    if operating_income is None:
        return None, {"method": "ROIC unavailable: Operating Income missing"}

    nopat = operating_income * (1 - tax_rate)
    invested_capital_values = _row_values(balance_sheet, "Invested Capital")
    invested_capital_source = "Yahoo Finance Invested Capital"

    if len(invested_capital_values) < 2:
        invested_capital_values = _derived_invested_capital(balance_sheet)
        invested_capital_source = "derived as Total Debt + Stockholders Equity - Cash and Short-Term Investments"

    if len(invested_capital_values) >= 2:
        ending_invested_capital = invested_capital_values[0]
        beginning_invested_capital = invested_capital_values[1]
        average_invested_capital = (ending_invested_capital + beginning_invested_capital) / 2
        capital_method = "average beginning and ending invested capital"
    elif invested_capital_values:
        ending_invested_capital = invested_capital_values[0]
        beginning_invested_capital = None
        average_invested_capital = ending_invested_capital
        capital_method = "ending invested capital only; prior period unavailable"
    else:
        return None, {
            "method": "ROIC unavailable: Invested Capital missing",
            "operating_income": operating_income,
            "tax_rate": tax_rate,
            "nopat": nopat,
        }

    if average_invested_capital <= 0:
        return None, {
            "method": "ROIC unavailable: average invested capital is not positive",
            "operating_income": operating_income,
            "tax_rate": tax_rate,
            "nopat": nopat,
            "average_invested_capital": average_invested_capital,
        }

    roic = nopat / average_invested_capital
    details = {
        "formula": "NOPAT / average invested capital",
        "capital_method": capital_method,
        "invested_capital_source": invested_capital_source,
        "tax_rate_source": tax_rate_source,
        "operating_income": operating_income,
        "tax_rate": tax_rate,
        "nopat": nopat,
        "beginning_invested_capital": beginning_invested_capital,
        "ending_invested_capital": ending_invested_capital,
        "average_invested_capital": average_invested_capital,
    }
    return roic, details


def _derived_invested_capital(balance_sheet: dict[str, list[float]]) -> list[float]:
    debts = balance_sheet.get("Total Debt", [])
    equities = balance_sheet.get("Stockholders Equity", [])
    cash_values = balance_sheet.get("Cash Cash Equivalents And Short Term Investments", [])
    values = []
    for debt, equity, cash in zip(debts, equities, cash_values):
        if debt is None or equity is None or cash is None:
            continue
        values.append(debt + equity - cash)
    return values


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str):
            number = float(value.replace(",", ""))
        else:
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


def _recent_insider_purchases(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        if frame.empty:
            return []
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=180)
        purchases = []
        for _, row in frame.iterrows():
            text = str(row.get("Text") or "")
            if "purchase" not in text.lower() and "buy" not in text.lower():
                continue
            date = row.get("Start Date")
            if date is None:
                continue
            date_value = date.to_pydatetime() if hasattr(date, "to_pydatetime") else date
            if getattr(date_value, "tzinfo", None) is not None:
                date_value = date_value.replace(tzinfo=None)
            if date_value < cutoff:
                continue
            purchases.append(
                {
                    "date": date_value.date().isoformat(),
                    "insider": str(row.get("Insider") or "Unknown"),
                    "position": str(row.get("Position") or "Unknown"),
                    "shares": _num(row.get("Shares")),
                    "value": _num(row.get("Value")),
                }
            )
        return purchases
    except Exception:
        return []


def _institutional_holders(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        if frame.empty:
            return []
        holders = []
        for _, row in frame.iterrows():
            percent = _num(row.get("pctHeld"))
            if percent is None or percent < 0.01:
                continue
            holders.append(
                {
                    "holder": str(row.get("Holder") or "Unknown"),
                    "percent_held": percent,
                    "shares": _num(row.get("Shares")),
                    "value": _num(row.get("Value")),
                }
            )
        return holders
    except Exception:
        return []
