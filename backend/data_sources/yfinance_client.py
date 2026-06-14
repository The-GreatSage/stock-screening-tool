from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    with ThreadPoolExecutor(max_workers=9) as executor:
        futures = {
            "info": executor.submit(_safe_dict_property, stock, "info"),
            "fast_info": executor.submit(_safe_fast_info, stock),
            "financials": executor.submit(_safe_frame_property, stock, "financials"),
            "quarterly_financials": executor.submit(_safe_frame_property, stock, "quarterly_financials"),
            "balance_sheet": executor.submit(_safe_frame_property, stock, "balance_sheet"),
            "cashflow": executor.submit(_safe_frame_property, stock, "cashflow"),
            "insider_transactions": executor.submit(_safe_frame_property_raw, stock, "insider_transactions"),
            "major_holders": executor.submit(_safe_frame_property_raw, stock, "major_holders"),
            "institutional_holders": executor.submit(_safe_frame_property_raw, stock, "institutional_holders"),
        }
        fetched = {name: future.result() for name, future in futures.items()}

    info = fetched["info"]
    fast_info = fetched["fast_info"]
    financials = fetched["financials"]
    quarterly_financials = fetched["quarterly_financials"]
    balance_sheet = fetched["balance_sheet"]
    cashflow = fetched["cashflow"]
    recent_insider_purchases, recent_insider_purchases_available = _recent_insider_purchases(
        fetched["insider_transactions"]
    )
    institutional_holders, institutional_holders_available = _institutional_holders(
        fetched["institutional_holders"]
    )

    revenue_history = _row_values(financials, "Total Revenue")
    earnings_history = _row_values(financials, "Net Income")
    margin_history = _margin_history(revenue_history, earnings_history)
    shares_history = _row_values(financials, "Diluted Average Shares") or _row_values(financials, "Basic Average Shares")
    share_repurchase_history = _row_values(cashflow, "Repurchase Of Capital Stock")

    quarterly_earnings = _latest(_row_values(quarterly_financials, "Net Income"))
    annual_earnings = _latest(earnings_history)
    latest_revenue = _latest(revenue_history)
    operating_income = _latest(_row_values(financials, "Operating Income"))
    latest_equity = _latest(_row_values(balance_sheet, "Stockholders Equity"))
    statement_cash = _latest(_row_values(balance_sheet, "Cash Cash Equivalents And Short Term Investments"))
    statement_debt = _latest(_row_values(balance_sheet, "Total Debt"))
    statement_shares = _latest(_row_values(balance_sheet, "Ordinary Shares Number"))
    diluted_shares = _latest(shares_history)

    shares_outstanding = _first_number(
        info.get("sharesOutstanding"),
        fast_info.get("shares"),
        statement_shares,
        diluted_shares,
    )
    market_cap = _first_number(info.get("marketCap"), fast_info.get("marketCap"))
    if market_cap is None:
        last_price = _num(fast_info.get("lastPrice"))
        if last_price is not None and shares_outstanding is not None:
            market_cap = last_price * shares_outstanding

    trailing_pe = _num(info.get("trailingPE"))
    if trailing_pe is None and market_cap is not None and annual_earnings is not None and annual_earnings > 0:
        trailing_pe = market_cap / annual_earnings

    profit_margin = _num(info.get("profitMargins"))
    if profit_margin is None and latest_revenue and annual_earnings is not None:
        profit_margin = annual_earnings / latest_revenue

    operating_margin = _num(info.get("operatingMargins"))
    if operating_margin is None and latest_revenue and operating_income is not None:
        operating_margin = operating_income / latest_revenue

    total_cash = _first_number(info.get("totalCash"), statement_cash)
    total_debt = _first_number(info.get("totalDebt"), statement_debt)
    debt_to_equity = _num(info.get("debtToEquity"))
    if debt_to_equity is None and total_debt is not None and latest_equity not in (None, 0):
        debt_to_equity = total_debt / latest_equity

    roic, roic_details = _calculate_roic(financials, balance_sheet)

    metrics = CompanyMetrics(
        ticker=symbol,
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        business_summary=info.get("longBusinessSummary"),
        market_cap=market_cap,
        trailing_pe=trailing_pe,
        forward_pe=_num(info.get("forwardPE")),
        peg_ratio=_num(info.get("pegRatio") or info.get("trailingPegRatio")),
        beta=_num(info.get("beta")),
        profit_margin=profit_margin,
        operating_margin=operating_margin,
        return_on_invested_capital=roic,
        roic_details=roic_details,
        total_cash=total_cash,
        total_debt=total_debt,
        debt_to_equity=debt_to_equity,
        quarterly_earnings=quarterly_earnings,
        annual_earnings=annual_earnings,
        revenue_history=list(reversed(revenue_history)),
        earnings_history=list(reversed(earnings_history)),
        margin_history=list(reversed(margin_history)),
        average_volume=_first_number(
            info.get("averageVolume"),
            info.get("averageDailyVolume10Day"),
            fast_info.get("threeMonthAverageVolume"),
            fast_info.get("tenDayAverageVolume"),
        ),
        shares_outstanding=shares_outstanding,
        shares_history=list(reversed(shares_history)),
        share_repurchase_history=list(reversed(share_repurchase_history)),
        insider_ownership=_first_number(
            info.get("heldPercentInsiders"),
            _major_holder_value(fetched["major_holders"], "insidersPercentHeld"),
        ),
        dividend_yield=_yield_decimal(info.get("dividendYield")),
        recent_insider_purchases=recent_insider_purchases,
        recent_insider_purchases_available=recent_insider_purchases_available,
        institutional_holders=institutional_holders,
        institutional_holders_available=institutional_holders_available,
        source_notes=_source_notes(info, fast_info, financials, balance_sheet),
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


def _safe_frame_property(stock: Any, name: str) -> dict[str, list[float]]:
    return _safe_frame_dict(_safe_property(stock, name))


def _safe_frame_property_raw(stock: Any, name: str) -> tuple[Any, bool]:
    value = _safe_property(stock, name)
    if value is None:
        return None, False
    return value, True


def _safe_property(stock: Any, name: str) -> Any:
    try:
        return getattr(stock, name, None)
    except Exception:
        return None


def _safe_dict_property(stock: Any, name: str) -> dict[str, Any]:
    value = _safe_property(stock, name)
    return value if isinstance(value, dict) else {}


def _safe_fast_info(stock: Any) -> dict[str, Any]:
    try:
        return dict(stock.fast_info)
    except Exception:
        return {}


def _source_notes(
    info: dict[str, Any],
    fast_info: dict[str, Any],
    financials: dict[str, list[float]],
    balance_sheet: dict[str, list[float]],
) -> list[str]:
    notes = ["Primary source: yfinance"]
    missing = []
    if not info:
        missing.append("company profile and some quote metrics")
    if not financials:
        missing.append("income statement")
    if not balance_sheet:
        missing.append("balance sheet")
    if missing:
        notes.append(
            "Yahoo blocked or did not return: "
            + ", ".join(missing)
            + ". Remaining unavailable filters are marked Unknown."
        )
    if not info and fast_info:
        notes.append("Price, market cap, volume, and shares were recovered from Yahoo fast price data.")
    if not info and financials:
        notes.append("Margins, P/E, cash, debt, and debt-to-equity were derived from financial statements where possible.")
    return notes


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


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _num(value)
        if number is not None:
            return number
    return None


def _yield_decimal(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if number > 0.2:
        return number / 100
    return number


def _recent_insider_purchases(frame_result: tuple[Any, bool]) -> tuple[list[dict[str, Any]], bool]:
    frame, available = frame_result
    if frame is None:
        return [], False
    try:
        if frame.empty:
            return [], available
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
        return purchases, available
    except Exception:
        return [], False


def _institutional_holders(frame_result: tuple[Any, bool]) -> tuple[list[dict[str, Any]], bool]:
    frame, available = frame_result
    if frame is None:
        return [], False
    try:
        if frame.empty:
            return [], available
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
        return holders, available
    except Exception:
        return [], False


def _major_holder_value(frame_result: tuple[Any, bool], row_name: str) -> float | None:
    frame, available = frame_result
    if not available or frame is None:
        return None
    try:
        if row_name not in frame.index:
            return None
        row = frame.loc[row_name]
        if hasattr(row, "iloc"):
            return _num(row.iloc[0])
        return _num(row)
    except Exception:
        return None
