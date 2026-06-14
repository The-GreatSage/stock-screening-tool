from __future__ import annotations

import math
from statistics import mean

from models import CompanyMetrics, Evaluation, RuleResult, RuleStatus


def evaluate_company(metrics: CompanyMetrics) -> Evaluation:
    rules = [
        _roic(metrics),
        _shareholder_yield_signal(metrics),
        _margins(metrics),
        _earnings_size(metrics),
        _valuation_pe_peg_pegy(metrics),
        _market_cap(metrics),
        _pe_end_of_run(metrics),
        _debt_to_equity(metrics),
        _yoy_revenue_growth(metrics),
        _insider_ownership(metrics),
        _margin_shrinkage(metrics),
        _recent_cluster_purchase(metrics),
        _constant_revenue_earnings_growth(metrics),
        _strategic_investors(metrics),
    ]
    score, max_score = score_rules(rules)
    return Evaluation(
        ticker=metrics.ticker,
        company_name=metrics.company_name,
        rating=rating_for_score(score, max_score, rules),
        score=score,
        max_score=max_score,
        rules=rules,
        metrics=metrics,
        source_notes=metrics.source_notes,
    )


def score_rules(rules: list[RuleResult]) -> tuple[int, int]:
    scored = [rule for rule in rules if rule.status not in {RuleStatus.UNKNOWN, RuleStatus.REVIEW}]
    max_score = sum(rule.weight for rule in scored)
    score = 0
    for rule in scored:
        if rule.status == RuleStatus.PASS:
            score += rule.weight
        elif rule.status == RuleStatus.WARNING:
            score += max(0, rule.weight // 2)
    return score, max_score


def rating_for_score(score: int, max_score: int, rules: list[RuleResult]) -> str:
    if max_score == 0:
        return "Needs More Data"
    failure_count = sum(1 for rule in rules if rule.status == RuleStatus.FAIL)
    warning_count = sum(1 for rule in rules if rule.status == RuleStatus.WARNING)
    ratio = score / max_score
    if ratio >= 0.8 and failure_count <= 2:
        return "Strong Candidate"
    if ratio >= 0.65:
        return "Watchlist Candidate"
    if ratio >= 0.5 or warning_count >= 3:
        return "Mixed / Needs Review"
    return "Weak Fit"


def _roic(metrics: CompanyMetrics) -> RuleResult:
    value = metrics.return_on_invested_capital
    if value is None:
        return unknown("roic", "ROIC", "ROIC data unavailable.", ">= 15%")
    return RuleResult(
        id="roic",
        name="ROIC",
        status=RuleStatus.PASS if value >= 0.15 else RuleStatus.FAIL,
        summary="Return on invested capital meets the target." if value >= 0.15 else "Return on invested capital is below target.",
        value={
            "roic": percent(value),
            "nopat": money(metrics.roic_details.get("nopat")),
            "average_invested_capital": money(metrics.roic_details.get("average_invested_capital")),
            "tax_rate": percent(metrics.roic_details.get("tax_rate")),
        },
        target=">= 15%",
        weight=3,
        details=metrics.roic_details.get("capital_method") or "ROIC inputs supplied directly.",
    )


def _margins(metrics: CompanyMetrics) -> RuleResult:
    profit = metrics.profit_margin
    operating = metrics.operating_margin
    if profit is None and operating is None:
        return unknown("margins", "Profit or operating margin", "Margin data unavailable.", "Profit >= 15% or operating >= 10%")
    passed = (profit is not None and profit >= 0.15) or (operating is not None and operating >= 0.10)
    value = {
        "profit_margin": percent(profit),
        "operating_margin": percent(operating),
    }
    return RuleResult(
        id="margins",
        name="Profit or operating margin",
        status=RuleStatus.PASS if passed else RuleStatus.FAIL,
        summary="Margins meet the quality threshold." if passed else "Margins are below the preferred threshold.",
        value=value,
        target="Profit >= 15% or operating >= 10%",
        weight=3,
    )


def _earnings_size(metrics: CompanyMetrics) -> RuleResult:
    q = metrics.quarterly_earnings
    annual = metrics.annual_earnings
    if q is None and annual is None:
        return unknown("earnings_size", "Earnings size", "Earnings data unavailable.", ">= $100M quarterly or >= $400M annually")
    passed = (q is not None and q >= 100_000_000) or (annual is not None and annual >= 400_000_000)
    return RuleResult(
        id="earnings_size",
        name="Earnings size",
        status=RuleStatus.PASS if passed else RuleStatus.FAIL,
        summary="Earnings clear the minimum size threshold." if passed else "Earnings are below the minimum size threshold.",
        value={"quarterly": money(q), "annual": money(annual)},
        target=">= $100M quarterly or >= $400M annually",
        weight=2,
    )


def _revenue_growth(metrics: CompanyMetrics) -> RuleResult:
    history = clean_series(metrics.revenue_history)
    if len(history) < 3:
        return unknown("revenue_growth", "Constant revenue growth", "Need at least three annual revenue values.", "Consistent growth, ideal 15-20%")
    growth_rates = growth(history)
    positive_years = sum(1 for value in growth_rates if value > 0)
    avg_growth = mean(growth_rates)
    if positive_years == len(growth_rates) and 0.15 <= avg_growth <= 0.20:
        status = RuleStatus.PASS
        summary = "Revenue has grown consistently and sits in the ideal growth range."
    elif positive_years == len(growth_rates):
        status = RuleStatus.PASS
        summary = "Revenue has grown consistently, though not in the ideal 15-20% range."
    elif positive_years >= len(growth_rates) - 1:
        status = RuleStatus.WARNING
        summary = "Revenue is mostly growing, with at least one weaker period."
    else:
        status = RuleStatus.FAIL
        summary = "Revenue growth is inconsistent."
    return RuleResult(
        id="revenue_growth",
        name="Constant revenue growth",
        status=status,
        summary=summary,
        value={"average_growth": percent(avg_growth), "growth_rates": [percent(v) for v in growth_rates]},
        target="Consistent growth, ideal 15-20%",
        weight=3,
    )


def _earnings_growth(metrics: CompanyMetrics) -> RuleResult:
    history = clean_series(metrics.earnings_history)
    if len(history) < 3:
        return unknown("earnings_growth", "Constant earnings growth", "Need at least three annual earnings values.", "Consistent growth")
    growth_rates = growth(history)
    positive_years = sum(1 for value in growth_rates if value > 0)
    if positive_years == len(growth_rates):
        status = RuleStatus.PASS
        summary = "Earnings have grown consistently."
    elif positive_years >= len(growth_rates) - 1:
        status = RuleStatus.WARNING
        summary = "Earnings are mostly growing, with at least one weaker period."
    else:
        status = RuleStatus.FAIL
        summary = "Earnings growth is inconsistent."
    return RuleResult(
        id="earnings_growth",
        name="Constant earnings growth",
        status=status,
        summary=summary,
        value={"growth_rates": [percent(v) for v in growth_rates]},
        target="Consistent growth",
        weight=3,
    )


def _cash_policy(metrics: CompanyMetrics) -> RuleResult:
    cash = metrics.total_cash
    debt = metrics.total_debt
    if cash is None and debt is None:
        return unknown("cash_policy", "Cash policy", "Cash and debt data unavailable.", "High cash and low/no debt")
    if debt in (None, 0):
        passed = cash is not None and cash > 0
        ratio = None
    else:
        ratio = cash / debt if cash is not None else None
        passed = ratio is not None and ratio >= 1
    status = RuleStatus.PASS if passed else RuleStatus.WARNING
    return RuleResult(
        id="cash_policy",
        name="Cash policy",
        status=status,
        summary="Cash covers debt." if passed else "Cash does not clearly cover debt.",
        value={"cash": money(cash), "debt": money(debt), "cash_to_debt": round(ratio, 2) if ratio is not None else None},
        target="High cash and low/no debt",
        weight=2,
    )


def _valuation_pe(metrics: CompanyMetrics) -> RuleResult:
    pe = first_present(metrics.trailing_pe, metrics.forward_pe)
    if pe is None:
        return unknown("pe_ratio", "P/E ratio", "P/E data unavailable.", "< 15")
    return RuleResult(
        id="pe_ratio",
        name="P/E ratio",
        status=RuleStatus.PASS if pe < 15 else RuleStatus.FAIL,
        summary="P/E is below the preferred cap." if pe < 15 else "P/E is above the preferred cap.",
        value=round(pe, 2),
        target="< 15",
        weight=2,
    )


def _valuation_peg(metrics: CompanyMetrics) -> RuleResult:
    peg = metrics.peg_ratio
    if peg is None:
        return unknown("peg_ratio", "PEG ratio", "PEG data unavailable.", "< 1")
    return RuleResult(
        id="peg_ratio",
        name="PEG ratio",
        status=RuleStatus.PASS if peg < 1 else RuleStatus.FAIL,
        summary="PEG is below 1." if peg < 1 else "PEG is not below 1.",
        value=round(peg, 2),
        target="< 1",
        weight=2,
    )


def _valuation_pe_peg_pegy(metrics: CompanyMetrics) -> RuleResult:
    pe = first_present(metrics.trailing_pe, metrics.forward_pe)
    peg = metrics.peg_ratio
    pegy = calculate_pegy(metrics, pe)
    if pe is None and peg is None and pegy is None:
        return unknown("valuation", "P/E, PEG, or PEGY", "Valuation data unavailable.", "P/E < 15 or PEG < 1 or PEGY < 1")

    pe_pass = pe is not None and pe < 15
    peg_pass = peg is not None and peg < 1
    pegy_pass = pegy is not None and pegy < 1
    passed = pe_pass or peg_pass or pegy_pass
    value = {
        "pe": round(pe, 2) if pe is not None else None,
        "peg": round(peg, 2) if peg is not None else None,
        "pegy": round(pegy, 2) if pegy is not None else None,
    }
    return RuleResult(
        id="valuation",
        name="P/E, PEG, or PEGY",
        status=RuleStatus.PASS if passed else RuleStatus.FAIL,
        summary="At least one valuation threshold is met." if passed else "P/E, PEG, and PEGY are all above the preferred thresholds.",
        value=value,
        target="P/E < 15 or PEG < 1 or PEGY < 1",
        weight=3,
        details="PEGY is approximated as P/E divided by the latest earnings growth percentage plus dividend yield percentage.",
    )


def _beta(metrics: CompanyMetrics) -> RuleResult:
    beta = metrics.beta
    if beta is None:
        return unknown("beta", "High beta", "Beta data unavailable.", ">= 1.2")
    status = RuleStatus.PASS if beta >= 1.2 else RuleStatus.WARNING
    return RuleResult(
        id="beta",
        name="High beta",
        status=status,
        summary="Beta is elevated." if beta >= 1.2 else "Beta is not especially high.",
        value=round(beta, 2),
        target=">= 1.2",
        weight=1,
        details="Alpha requires benchmark-relative return calculation and will be added with price-history support.",
    )


def _market_cap(metrics: CompanyMetrics) -> RuleResult:
    cap = metrics.market_cap
    if cap is None:
        return unknown("market_cap", "Decent market cap", "Market cap data unavailable.", "$100M-$7B, preferred above $200M")
    if cap > 7_000_000_000:
        status = RuleStatus.FAIL
        summary = "Market cap is above the maximum size limit."
    elif cap < 100_000_000:
        status = RuleStatus.FAIL
        summary = "Market cap is below the minimum size limit."
    elif cap < 200_000_000:
        status = RuleStatus.WARNING
        summary = "Market cap is acceptable but below the preferred $200M floor."
    else:
        status = RuleStatus.PASS
        summary = "Market cap is within the target range."
    return RuleResult(
        id="market_cap",
        name="Decent market cap",
        status=status,
        summary=summary,
        value=money(cap),
        target="$100M-$7B, preferred above $200M",
        weight=2,
    )


def _debt_to_equity(metrics: CompanyMetrics) -> RuleResult:
    dte = metrics.debt_to_equity
    if dte is None:
        return unknown("debt_to_equity", "Debt-to-equity", "Debt-to-equity data unavailable.", "< 0.5")
    normalized = dte / 100 if dte > 10 else dte
    return RuleResult(
        id="debt_to_equity",
        name="Debt-to-equity",
        status=RuleStatus.PASS if normalized < 0.5 else RuleStatus.FAIL,
        summary="Debt-to-equity is below 0.5." if normalized < 0.5 else "Debt-to-equity is too high.",
        value=round(normalized, 2),
        target="< 0.5",
        weight=3,
    )


def _margin_shrinkage(metrics: CompanyMetrics) -> RuleResult:
    revenue = clean_series(metrics.revenue_history)
    margins = clean_series(metrics.margin_history)
    if len(revenue) < 2 or len(margins) < 2:
        return unknown("margin_shrinkage", "Margin shrinkage red flag", "Need revenue and net profit history from financial statements or 10-K.", "Avoid shrinking margin while revenue grows")
    revenue_growing = revenue[-1] > revenue[0]
    margins_shrinking = margins[-1] < margins[0]
    if revenue_growing and margins_shrinking:
        status = RuleStatus.WARNING
        summary = "Revenue is growing while margins are shrinking."
    else:
        status = RuleStatus.PASS
        summary = "No obvious revenue-growth/margin-shrinkage red flag."
    return RuleResult(
        id="margin_shrinkage",
        name="Margin shrinkage red flag",
        status=status,
        summary=summary,
        value={"first_margin": percent(margins[0]), "latest_margin": percent(margins[-1])},
        target="Avoid shrinking margin while revenue grows",
        weight=2,
        details="Uses available annual revenue and net-income margin data; this should later be cross-checked against the 10-K.",
    )


def _volume(metrics: CompanyMetrics) -> RuleResult:
    volume = metrics.average_volume
    if volume is None:
        return unknown("volume", "Trading volume", "Average volume unavailable.", "Enough liquidity for intended position size")
    status = RuleStatus.PASS if volume >= 100_000 else RuleStatus.WARNING
    return RuleResult(
        id="volume",
        name="Trading volume",
        status=status,
        summary="Average volume looks liquid enough for an initial screen." if volume >= 100_000 else "Average volume may be thin.",
        value=compact_number(volume),
        target=">= 100K avg volume",
        weight=1,
    )


def _shareholder_yield_signal(metrics: CompanyMetrics) -> RuleResult:
    history = clean_series(metrics.shares_history)
    repurchases = clean_series(metrics.share_repurchase_history)
    if len(history) >= 2:
        change = (history[-1] - history[0]) / abs(history[0])
        if change < -0.02:
            status = RuleStatus.PASS
            summary = "Diluted share count appears to be decreasing."
        elif change > 0.05:
            status = RuleStatus.FAIL
            summary = "Diluted share count appears to be rising materially."
        else:
            status = RuleStatus.WARNING
            summary = "Diluted share count is mostly flat."
        value = {"share_count_change": percent(change)}
    elif repurchases:
        latest_repurchase = repurchases[-1]
        status = RuleStatus.PASS if latest_repurchase < 0 else RuleStatus.WARNING
        summary = "Recent cash-flow statement shows share repurchases." if latest_repurchase < 0 else "Share repurchase signal is not clear."
        value = {"latest_repurchase_cash_flow": money(latest_repurchase)}
    else:
        return unknown("buyback_dilution", "Cash buyback", "Need share-count or repurchase history.", "Prefer cash repurchases or falling share count")
    return RuleResult(
        id="buyback_dilution",
        name="Cash buyback",
        status=status,
        summary=summary,
        value=value,
        target="Prefer cash repurchases or falling share count",
        weight=2,
    )


def _insider_ownership(metrics: CompanyMetrics) -> RuleResult:
    ownership = metrics.insider_ownership
    if ownership is None:
        return unknown("insider_ownership", "Insider ownership", "Insider ownership unavailable.", "> 5%")
    return RuleResult(
        id="insider_ownership",
        name="Insider ownership",
        status=RuleStatus.PASS if ownership > 0.05 else RuleStatus.FAIL,
        summary="Insider ownership is above 5%." if ownership > 0.05 else "Insider ownership is below 5%.",
        value=percent(ownership),
        target="> 5%",
        weight=2,
        details=metrics.insider_ownership_source,
    )


def _yoy_revenue_growth(metrics: CompanyMetrics) -> RuleResult:
    history = clean_series(metrics.revenue_history)
    if len(history) < 2:
        return unknown("yoy_revenue_growth", "Year-over-year revenue growth", "Need at least two annual revenue values.", "15-20% YoY")
    latest_growth = (history[-1] - history[-2]) / abs(history[-2]) if history[-2] else None
    if latest_growth is None:
        return unknown("yoy_revenue_growth", "Year-over-year revenue growth", "Prior-year revenue is zero.", "15-20% YoY")
    if 0.15 <= latest_growth <= 0.20:
        status = RuleStatus.PASS
        summary = "Latest year-over-year revenue growth is in the ideal 15-20% range."
    elif latest_growth > 0:
        status = RuleStatus.WARNING
        summary = "Revenue is growing, but not in the ideal 15-20% range."
    else:
        status = RuleStatus.FAIL
        summary = "Latest year-over-year revenue growth is negative."
    return RuleResult(
        id="yoy_revenue_growth",
        name="Year-over-year revenue growth",
        status=status,
        summary=summary,
        value={"latest_yoy_growth": percent(latest_growth)},
        target="15-20% YoY",
        weight=2,
    )


def _recent_cluster_purchase(metrics: CompanyMetrics) -> RuleResult:
    purchases = metrics.recent_insider_purchases
    if not metrics.recent_insider_purchases_available:
        return unknown(
            "recent_cluster_purchase",
            "Recent cluster purchase",
            "Recent insider transaction data unavailable.",
            "Purchases by at least 2 distinct insiders within 180 days",
        )
    if not purchases:
        return RuleResult(
            id="recent_cluster_purchase",
            name="Recent cluster purchase",
            status=RuleStatus.FAIL,
            summary="No recent open-market insider purchases were found.",
            value={"distinct_insiders": 0, "purchase_count": 0},
            target="Purchases by at least 2 distinct insiders within 180 days",
            weight=2,
        )
    insiders = {str(item.get("insider", "")).strip() for item in purchases if item.get("insider")}
    total_value = sum(float(item.get("value") or 0) for item in purchases)
    if len(insiders) >= 2:
        status = RuleStatus.PASS
        summary = "Multiple distinct insiders made recent purchases."
    else:
        status = RuleStatus.WARNING
        summary = "A recent insider purchase was found, but it is not a cluster."
    return RuleResult(
        id="recent_cluster_purchase",
        name="Recent cluster purchase",
        status=status,
        summary=summary,
        value={
            "distinct_insiders": len(insiders),
            "purchase_count": len(purchases),
            "total_value": money(total_value),
            "purchases": purchases[:5],
        },
        target="Purchases by at least 2 distinct insiders within 180 days",
        weight=2,
    )


def _constant_revenue_earnings_growth(metrics: CompanyMetrics) -> RuleResult:
    revenues = clean_series(metrics.revenue_history)
    earnings = clean_series(metrics.earnings_history)
    if len(revenues) < 3 or len(earnings) < 3:
        return unknown(
            "constant_revenue_earnings_growth",
            "Constant revenue and earnings growth",
            "Need at least three annual revenue and earnings values.",
            "Both revenue and earnings grow consistently",
        )
    revenue_rates = growth(revenues)
    earnings_rates = growth(earnings)
    revenue_positive = sum(rate > 0 for rate in revenue_rates)
    earnings_positive = sum(rate > 0 for rate in earnings_rates)
    if revenue_positive == len(revenue_rates) and earnings_positive == len(earnings_rates):
        status = RuleStatus.PASS
        summary = "Revenue and earnings have grown in every available annual period."
    elif revenue_positive >= len(revenue_rates) - 1 and earnings_positive >= len(earnings_rates) - 1:
        status = RuleStatus.WARNING
        summary = "Revenue and earnings are mostly growing, with at least one weaker period."
    else:
        status = RuleStatus.FAIL
        summary = "Revenue and earnings growth are not consistently positive."
    return RuleResult(
        id="constant_revenue_earnings_growth",
        name="Constant revenue and earnings growth",
        status=status,
        summary=summary,
        value={
            "revenue_growth": [percent(rate) for rate in revenue_rates],
            "earnings_growth": [percent(rate) for rate in earnings_rates],
        },
        target="Both revenue and earnings grow consistently",
        weight=3,
    )


def _strategic_investors(metrics: CompanyMetrics) -> RuleResult:
    holders = metrics.institutional_holders
    if not metrics.institutional_holders_available:
        return unknown(
            "strategic_investors",
            "Strategic investors",
            "Institutional holder data unavailable.",
            "Major institution >= 1% or any investor >= 5%",
        )
    if not holders:
        return RuleResult(
            id="strategic_investors",
            name="Strategic investors",
            status=RuleStatus.FAIL,
            summary="No institutional holder owning at least 1% was found.",
            value={"qualifying_count": 0, "holders": []},
            target="Major institution >= 1% or any investor >= 5%",
            weight=2,
        )
    major_terms = (
        "blackrock",
        "vanguard",
        "state street",
        "fidelity",
        "capital group",
        "capital management",
        "geode",
        "jpmorgan",
        "j.p. morgan",
        "goldman sachs",
        "morgan stanley",
        "berkshire",
        "t. rowe",
        "invesco",
        "ubs",
        "norges bank",
    )
    strategic = [
        holder
        for holder in holders
        if holder.get("percent_held", 0) >= 0.05
        or any(term in str(holder.get("holder", "")).lower() for term in major_terms)
    ]
    if strategic:
        status = RuleStatus.PASS
        summary = "Sizable positions from major institutions or strategic holders were found."
    else:
        status = RuleStatus.WARNING
        summary = "Sizable institutional positions exist, but none clearly qualify as strategic."
    display_holders = strategic or holders
    return RuleResult(
        id="strategic_investors",
        name="Strategic investors",
        status=status,
        summary=summary,
        value={
            "qualifying_count": len(strategic),
            "holders": [
                {
                    "holder": holder.get("holder"),
                    "percent_held": percent(holder.get("percent_held")),
                    "value": money(holder.get("value")),
                }
                for holder in display_holders[:5]
            ],
        },
        target="Major institution >= 1% or any investor >= 5%",
        weight=2,
        details="Industry expertise cannot be confirmed from holder names alone and should be reviewed manually.",
    )


def _pe_end_of_run(metrics: CompanyMetrics) -> RuleResult:
    pe = first_present(metrics.trailing_pe, metrics.forward_pe)
    if pe is None:
        return unknown("pe_end_of_run", "P/E end-of-run warning", "P/E data unavailable.", "Warning at 40-50")
    if 40 <= pe <= 50:
        return RuleResult(
            id="pe_end_of_run",
            name="P/E end-of-run warning",
            status=RuleStatus.WARNING,
            summary="P/E sits in the 40-50 warning zone.",
            value=round(pe, 2),
            target="Warning at 40-50",
            weight=1,
        )
    return RuleResult(
        id="pe_end_of_run",
        name="P/E end-of-run warning",
        status=RuleStatus.PASS,
        summary="P/E is not in the 40-50 warning zone.",
        value=round(pe, 2),
        target="Warning at 40-50",
        weight=1,
    )


def calculate_pegy(metrics: CompanyMetrics, pe: float | None) -> float | None:
    if pe is None:
        return None
    earnings = clean_series(metrics.earnings_history)
    earnings_growth = None
    if len(earnings) >= 2 and earnings[-2] != 0:
        earnings_growth = (earnings[-1] - earnings[-2]) / abs(earnings[-2])
    if earnings_growth is None or earnings_growth <= 0:
        return None
    dividend_yield = metrics.dividend_yield
    if dividend_yield is None:
        dividend_yield = 0
    if dividend_yield > 0.2:
        dividend_yield = dividend_yield / 100
    growth_plus_yield_percentage = (earnings_growth + dividend_yield) * 100
    if growth_plus_yield_percentage <= 0:
        return None
    return pe / growth_plus_yield_percentage


def _trend_friend(metrics: CompanyMetrics) -> RuleResult:
    text_parts = [
        metrics.sector or "",
        metrics.industry or "",
        metrics.business_summary or "",
    ]
    haystack = f" {' '.join(text_parts).lower()} "
    if not haystack.strip():
        return unknown("trend_friend", "Trend is friend: tech/AI relevance", "Sector, industry, and company description unavailable.", "Technology sector or AI-related business")

    direct_terms = [
        "technology",
        "artificial intelligence",
        "machine learning",
        "generative ai",
        " ai ",
        " ai-",
        " ai,",
        " ai.",
        "semiconductor",
        "software",
        "cloud",
        "data center",
        "data centre",
        "gpu",
        "accelerated computing",
        "automation",
        "robotics",
        "analytics",
        "cybersecurity",
    ]
    adjacent_terms = [
        "internet",
        "digital",
        "platform",
        "e-commerce",
        "electronic",
        "network",
        "communications",
        "devices",
    ]

    matched = [term.strip(" ,.-") for term in direct_terms if term in haystack]
    if matched:
        return RuleResult(
            id="trend_friend",
            name="Trend is friend: tech/AI relevance",
            status=RuleStatus.PASS,
            summary="Company appears to be in technology or directly tied to AI-related themes.",
            value={
                "sector": metrics.sector,
                "industry": metrics.industry,
                "matched_terms": sorted(set(matched)),
            },
            target="Technology sector or AI-related business",
            weight=1,
        )

    adjacent = [term for term in adjacent_terms if term in haystack]
    if adjacent:
        return RuleResult(
            id="trend_friend",
            name="Trend is friend: tech/AI relevance",
            status=RuleStatus.WARNING,
            summary="Company has some technology-adjacent language but is not clearly tech or AI-led.",
            value={
                "sector": metrics.sector,
                "industry": metrics.industry,
                "matched_terms": sorted(set(adjacent)),
            },
            target="Technology sector or AI-related business",
            weight=1,
        )

    return RuleResult(
        id="trend_friend",
        name="Trend is friend: tech/AI relevance",
        status=RuleStatus.FAIL,
        summary="Company does not appear to be technology or AI-related from the available profile.",
        value={"sector": metrics.sector, "industry": metrics.industry},
        target="Technology sector or AI-related business",
        weight=1,
    )


def unknown(rule_id: str, name: str, summary: str, target: str) -> RuleResult:
    return RuleResult(id=rule_id, name=name, status=RuleStatus.UNKNOWN, summary=summary, target=target, weight=0)


def clean_series(values: list[float]) -> list[float]:
    cleaned = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def growth(values: list[float]) -> list[float]:
    rates = []
    for prior, current in zip(values, values[1:]):
        if prior == 0:
            continue
        rates.append((current - prior) / abs(prior))
    return rates


def first_present(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def percent(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value * 100:.1f}%"


def money(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.2f}K"
    return f"{sign}${value:.2f}"


def compact_number(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.2f}K"
    return str(round(value, 2))
