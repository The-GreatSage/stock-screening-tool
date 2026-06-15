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
    with ThreadPoolExecutor(max_workers=13) as executor:
        futures = {
            "info": executor.submit(_safe_dict_property, stock, "info"),
            "fast_info": executor.submit(_safe_fast_info, stock),
            "financials": executor.submit(_safe_frame_property, stock, "financials"),
            "quarterly_financials_raw": executor.submit(_safe_property, stock, "quarterly_financials"),
            "ttm_income_stmt": executor.submit(_safe_frame_property, stock, "ttm_income_stmt"),
            "balance_sheet": executor.submit(_safe_frame_property, stock, "balance_sheet"),
            "quarterly_balance_sheet": executor.submit(_safe_frame_property, stock, "quarterly_balance_sheet"),
            "cashflow": executor.submit(_safe_frame_property, stock, "cashflow"),
            "insider_transactions": executor.submit(_safe_frame_property_raw, stock, "insider_transactions"),
            "major_holders": executor.submit(_safe_frame_property_raw, stock, "major_holders"),
            "institutional_holders": executor.submit(_safe_frame_property_raw, stock, "institutional_holders"),
            "news": executor.submit(_safe_news, stock),
            "earnings_dates": executor.submit(_safe_earnings_dates, stock),
        }
        fetched = {name: future.result() for name, future in futures.items()}

    info = fetched["info"]
    fast_info = fetched["fast_info"]
    financials = fetched["financials"]
    quarterly_financials_raw = fetched["quarterly_financials_raw"]
    quarterly_financials = _safe_frame_dict(quarterly_financials_raw)
    ttm_income_stmt = fetched["ttm_income_stmt"]
    balance_sheet = fetched["balance_sheet"]
    quarterly_balance_sheet = fetched["quarterly_balance_sheet"]
    cashflow = fetched["cashflow"]
    recent_insider_purchases, recent_insider_purchases_available = _recent_insider_purchases(
        fetched["insider_transactions"]
    )
    institutional_holders, institutional_holders_available = _institutional_holders(
        fetched["institutional_holders"]
    )
    recent_earnings_reports = _recent_earnings_reports(fetched["earnings_dates"])
    if not recent_earnings_reports:
        recent_earnings_reports = _quarterly_reports(quarterly_financials_raw)

    revenue_history = _row_values(financials, "Total Revenue")
    earnings_history = _row_values(financials, "Net Income")
    margin_history = _margin_history(revenue_history, earnings_history)
    shares_history = _row_values(financials, "Diluted Average Shares") or _row_values(financials, "Basic Average Shares")
    share_repurchase_history = _row_values(cashflow, "Repurchase Of Capital Stock")

    quarterly_earnings = _latest(_row_values(quarterly_financials, "Net Income"))
    trailing_earnings = _first_number(
        _latest(_row_values(ttm_income_stmt, "Net Income")),
        _sum_latest(_row_values(quarterly_financials, "Net Income"), 4),
    )
    trailing_diluted_eps = _first_number(
        _latest(_row_values(ttm_income_stmt, "Diluted EPS")),
        _sum_latest(_row_values(quarterly_financials, "Diluted EPS"), 4),
    )
    latest_fiscal_earnings = _latest(earnings_history)
    annual_earnings = _first_number(trailing_earnings, latest_fiscal_earnings)
    annual_earnings_source = (
        "Latest four quarters net income" if trailing_earnings is not None else "Latest fiscal-year net income"
    )
    latest_revenue = _latest(revenue_history)
    operating_income = _latest(_row_values(financials, "Operating Income"))
    ttm_revenue = _latest(_row_values(ttm_income_stmt, "Total Revenue"))
    ttm_net_income = _latest(_row_values(ttm_income_stmt, "Net Income"))
    ttm_operating_income = _latest(_row_values(ttm_income_stmt, "Operating Income"))
    latest_equity = _first_number(
        _latest(_row_values(quarterly_balance_sheet, "Stockholders Equity")),
        _latest(_row_values(balance_sheet, "Stockholders Equity")),
    )
    statement_cash = _first_number(
        _latest_from_rows(
            quarterly_balance_sheet,
            "Cash Cash Equivalents And Short Term Investments",
            "Cash Cash Equivalents And Federal Funds Sold",
            "Cash And Cash Equivalents",
        ),
        _latest_from_rows(
            balance_sheet,
            "Cash Cash Equivalents And Short Term Investments",
            "Cash Cash Equivalents And Federal Funds Sold",
            "Cash And Cash Equivalents",
        ),
    )
    statement_debt = _first_number(
        _latest(_row_values(quarterly_balance_sheet, "Total Debt")),
        _latest(_row_values(balance_sheet, "Total Debt")),
    )
    statement_shares = _latest(_row_values(balance_sheet, "Ordinary Shares Number"))
    diluted_shares = _latest(shares_history)

    shares_outstanding = _num(info.get("sharesOutstanding"))
    shares_outstanding_source = "Yahoo reported shares outstanding" if shares_outstanding is not None else None
    if shares_outstanding is None:
        shares_outstanding = _num(fast_info.get("shares"))
        shares_outstanding_source = "Yahoo fast price shares" if shares_outstanding is not None else None
    if shares_outstanding is None:
        shares_outstanding = _first_number(statement_shares, diluted_shares)
        shares_outstanding_source = "Latest statement share count" if shares_outstanding is not None else None
    market_cap = _first_number(info.get("marketCap"), fast_info.get("marketCap"))
    if market_cap is None:
        last_price = _num(fast_info.get("lastPrice"))
        if last_price is not None and shares_outstanding is not None:
            market_cap = last_price * shares_outstanding

    trailing_pe = _num(info.get("trailingPE"))
    trailing_pe_source = "Yahoo reported trailing P/E" if trailing_pe is not None else None
    last_price = _first_number(info.get("regularMarketPrice"), fast_info.get("lastPrice"))
    if trailing_pe is None and last_price is not None and trailing_diluted_eps is not None and trailing_diluted_eps > 0:
        trailing_pe = last_price / trailing_diluted_eps
        trailing_pe_source = "Derived as current price / latest four quarters diluted EPS"
    if trailing_pe is None and market_cap is not None and trailing_earnings is not None and trailing_earnings > 0:
        trailing_pe = market_cap / trailing_earnings
        trailing_pe_source = "Derived as market cap / latest four quarters net income"

    profit_margin = _num(info.get("profitMargins"))
    profit_margin_source = "Yahoo reported TTM profit margin" if profit_margin is not None else None
    if profit_margin is None and ttm_revenue and ttm_net_income is not None:
        profit_margin = ttm_net_income / ttm_revenue
        profit_margin_source = "Derived as TTM net income / TTM revenue"
    elif profit_margin is None and latest_revenue and latest_fiscal_earnings is not None:
        profit_margin = latest_fiscal_earnings / latest_revenue
        profit_margin_source = "Derived as latest annual net income / revenue"

    operating_margin = _num(info.get("operatingMargins"))
    operating_margin_source = "Yahoo reported TTM operating margin" if operating_margin is not None else None
    if operating_margin is None and ttm_revenue and ttm_operating_income is not None:
        operating_margin = ttm_operating_income / ttm_revenue
        operating_margin_source = "Derived as TTM operating income / TTM revenue"
    elif operating_margin is None and latest_revenue and operating_income is not None:
        operating_margin = operating_income / latest_revenue
        operating_margin_source = "Derived as latest annual operating income / revenue"

    total_cash = _num(info.get("totalCash"))
    total_cash_source = "Yahoo reported total cash" if total_cash is not None else None
    if total_cash is None:
        total_cash = statement_cash
        total_cash_source = "Latest quarterly balance-sheet cash" if total_cash is not None else None
    total_debt = _num(info.get("totalDebt"))
    total_debt_source = "Yahoo reported total debt" if total_debt is not None else None
    if total_debt is None:
        total_debt = statement_debt
        total_debt_source = "Latest quarterly balance-sheet total debt" if total_debt is not None else None
    debt_to_equity = _percent_to_ratio(info.get("debtToEquity"))
    debt_to_equity_source = "Yahoo reported debt-to-equity" if debt_to_equity is not None else None
    if debt_to_equity is None and total_debt is not None and latest_equity not in (None, 0):
        debt_to_equity = total_debt / latest_equity
        debt_to_equity_source = "Derived from latest quarterly debt / stockholders equity"

    roic, roic_details = _calculate_roic(financials, balance_sheet)

    metrics = CompanyMetrics(
        ticker=symbol,
        company_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        business_summary=info.get("longBusinessSummary"),
        market_cap=market_cap,
        trailing_pe=trailing_pe,
        trailing_pe_source=trailing_pe_source,
        forward_pe=_num(info.get("forwardPE")),
        peg_ratio=_num(info.get("pegRatio") or info.get("trailingPegRatio")),
        beta=_num(info.get("beta")),
        profit_margin=profit_margin,
        profit_margin_source=profit_margin_source,
        operating_margin=operating_margin,
        operating_margin_source=operating_margin_source,
        return_on_invested_capital=roic,
        roic_details=roic_details,
        total_cash=total_cash,
        total_cash_source=total_cash_source,
        total_debt=total_debt,
        total_debt_source=total_debt_source,
        debt_to_equity=debt_to_equity,
        debt_to_equity_source=debt_to_equity_source,
        quarterly_earnings=quarterly_earnings,
        annual_earnings=annual_earnings,
        annual_earnings_source=annual_earnings_source,
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
        shares_outstanding_source=shares_outstanding_source,
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
        recent_news=_recent_news(fetched["news"]),
        recent_earnings_reports=recent_earnings_reports,
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


def _safe_news(stock: Any) -> list[dict[str, Any]]:
    try:
        news = stock.get_news(count=6, tab="news")
        return news if isinstance(news, list) else []
    except Exception:
        return []


def _safe_earnings_dates(stock: Any) -> Any:
    try:
        return stock.get_earnings_dates(limit=16)
    except Exception:
        return None


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


def _latest_from_rows(data: dict[str, list[float]], *names: str) -> float | None:
    for name in names:
        value = _latest(_row_values(data, name))
        if value is not None:
            return value
    return None


def _sum_latest(values: list[float], count: int) -> float | None:
    if len(values) < count:
        return None
    return sum(values[:count])


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


def _percent_to_ratio(value: Any) -> float | None:
    number = _num(value)
    return number / 100 if number is not None else None


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


def _recent_news(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    news = []
    for item in records:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = _text_value(content.get("title"))
        if not title:
            continue
        provider = content.get("provider")
        publisher = (
            _text_value(provider.get("displayName"))
            if isinstance(provider, dict)
            else _text_value(content.get("publisher"))
        )
        url = _nested_url(content.get("canonicalUrl")) or _nested_url(content.get("clickThroughUrl"))
        published = _iso_date(content.get("pubDate") or content.get("providerPublishTime"))
        news.append(
            {
                "title": title,
                "publisher": publisher or "Yahoo Finance",
                "published": published,
                "url": url,
            }
        )
        if len(news) == 5:
            break
    return news


def _recent_earnings_reports(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        if frame.empty:
            return []
        reports = []
        for index, row in frame.iterrows():
            reported_eps = _num(row.get("Reported EPS"))
            if reported_eps is None:
                continue
            reports.append(
                {
                    "date": _iso_date(index),
                    "reported_eps": reported_eps,
                    "eps_estimate": _num(row.get("EPS Estimate")),
                    "surprise_percent": _num(row.get("Surprise(%)")),
                }
            )
        reports.sort(key=lambda report: report.get("date") or "", reverse=True)
        return reports[:5]
    except Exception:
        return []


def _quarterly_reports(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        if frame.empty:
            return []
        reports = []
        for column in frame.columns:
            revenue = _frame_number(frame, "Total Revenue", column)
            net_income = _frame_number(frame, "Net Income", column)
            diluted_eps = _frame_number(frame, "Diluted EPS", column)
            if revenue is None and net_income is None and diluted_eps is None:
                continue
            reports.append(
                {
                    "date": _iso_date(column),
                    "reported_eps": diluted_eps,
                    "revenue": revenue,
                    "net_income": net_income,
                }
            )
        reports.sort(key=lambda report: report.get("date") or "", reverse=True)
        return reports[:5]
    except Exception:
        return []


def _frame_number(frame: Any, row_name: str, column: Any) -> float | None:
    if row_name not in frame.index:
        return None
    return _num(frame.loc[row_name, column])


def _nested_url(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("url")
    text = _text_value(value)
    return text if text and text.startswith(("https://", "http://")) else None


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = _text_value(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else text


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
