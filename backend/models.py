from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuleStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    UNKNOWN = "unknown"
    REVIEW = "review"


@dataclass
class RuleResult:
    id: str
    name: str
    status: RuleStatus
    summary: str
    value: Any = None
    target: str | None = None
    weight: int = 1
    details: str | None = None


@dataclass
class CompanyMetrics:
    ticker: str
    sec_cik: str | None = None
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    business_summary: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    trailing_pe_source: str | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    beta: float | None = None
    profit_margin: float | None = None
    profit_margin_source: str | None = None
    operating_margin: float | None = None
    operating_margin_source: str | None = None
    return_on_invested_capital: float | None = None
    roic_details: dict[str, Any] = field(default_factory=dict)
    total_cash: float | None = None
    total_cash_source: str | None = None
    total_debt: float | None = None
    total_debt_source: str | None = None
    debt_to_equity: float | None = None
    debt_to_equity_source: str | None = None
    quarterly_earnings: float | None = None
    annual_earnings: float | None = None
    annual_earnings_source: str | None = None
    revenue_history: list[float] = field(default_factory=list)
    earnings_history: list[float] = field(default_factory=list)
    margin_history: list[float] = field(default_factory=list)
    average_volume: float | None = None
    shares_outstanding: float | None = None
    shares_outstanding_source: str | None = None
    shares_history: list[float] = field(default_factory=list)
    share_repurchase_history: list[float] = field(default_factory=list)
    insider_ownership: float | None = None
    insider_ownership_source: str | None = None
    dividend_yield: float | None = None
    recent_insider_purchases: list[dict[str, Any]] = field(default_factory=list)
    recent_insider_purchases_available: bool = False
    institutional_holders: list[dict[str, Any]] = field(default_factory=list)
    institutional_holders_available: bool = False
    recent_news: list[dict[str, Any]] = field(default_factory=list)
    recent_earnings_reports: list[dict[str, Any]] = field(default_factory=list)
    source_notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evaluation:
    ticker: str
    company_name: str | None
    rating: str
    score: int
    max_score: int
    rules: list[RuleResult]
    metrics: CompanyMetrics
    source_notes: list[str]
