import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from evaluator import evaluate_company
from data_sources.yfinance_client import _calculate_roic
from models import CompanyMetrics


class EvaluatorTest(unittest.TestCase):
    def test_roic_uses_average_invested_capital(self):
        roic, details = _calculate_roic(
            {
                "Operating Income": [120.0],
                "Pretax Income": [100.0],
                "Tax Provision": [20.0],
            },
            {"Invested Capital": [500.0, 300.0]},
        )

        self.assertAlmostEqual(roic, 0.24)
        self.assertEqual(details["nopat"], 96.0)
        self.assertEqual(details["average_invested_capital"], 400.0)

    def test_quality_small_cap_scores_as_candidate(self):
        metrics = CompanyMetrics(
            ticker="TEST",
            company_name="Test Company",
            sector="Technology",
            industry="Software",
            business_summary="The company builds AI software for enterprise automation.",
            market_cap=1_500_000_000,
            trailing_pe=12,
            peg_ratio=0.8,
            beta=1.4,
            profit_margin=0.18,
            operating_margin=0.16,
            return_on_invested_capital=0.22,
            roic_details={
                "nopat": 220_000_000,
                "average_invested_capital": 1_000_000_000,
                "tax_rate": 0.21,
                "capital_method": "average beginning and ending invested capital",
            },
            total_cash=300_000_000,
            total_debt=100_000_000,
            debt_to_equity=0.2,
            quarterly_earnings=120_000_000,
            annual_earnings=520_000_000,
            revenue_history=[400_000_000, 470_000_000, 550_000_000, 640_000_000],
            earnings_history=[80_000_000, 100_000_000, 125_000_000, 150_000_000],
            margin_history=[0.20, 0.21, 0.22, 0.23],
            average_volume=500_000,
            shares_history=[100_000_000, 98_000_000, 95_000_000],
            insider_ownership=0.08,
            recent_insider_purchases=[
                {"date": "2026-05-01", "insider": "Director One", "value": 500_000},
                {"date": "2026-05-08", "insider": "Director Two", "value": 750_000},
            ],
            recent_insider_purchases_available=True,
            institutional_holders=[
                {"holder": "BlackRock Inc.", "percent_held": 0.06, "value": 90_000_000},
            ],
            institutional_holders_available=True,
        )

        evaluation = evaluate_company(metrics)

        self.assertEqual(evaluation.rating, "Strong Candidate")
        self.assertGreaterEqual(evaluation.score / evaluation.max_score, 0.8)
        self.assertEqual(_status(evaluation, "roic"), "pass")
        self.assertEqual(_status(evaluation, "buyback_dilution"), "pass")
        self.assertEqual(_status(evaluation, "valuation"), "pass")
        self.assertEqual(_status(evaluation, "market_cap"), "pass")
        self.assertEqual(_status(evaluation, "debt_to_equity"), "pass")
        self.assertEqual(_status(evaluation, "yoy_revenue_growth"), "pass")
        self.assertEqual(_status(evaluation, "insider_ownership"), "pass")
        self.assertEqual(_status(evaluation, "margin_shrinkage"), "pass")
        self.assertEqual(_status(evaluation, "recent_cluster_purchase"), "pass")
        self.assertEqual(_status(evaluation, "constant_revenue_earnings_growth"), "pass")
        self.assertEqual(_status(evaluation, "strategic_investors"), "pass")

    def test_ownership_filters_distinguish_empty_from_unavailable(self):
        available = evaluate_company(
            CompanyMetrics(
                ticker="EMPTY",
                recent_insider_purchases_available=True,
                institutional_holders_available=True,
            )
        )
        unavailable = evaluate_company(CompanyMetrics(ticker="BLOCKED"))

        self.assertEqual(_status(available, "recent_cluster_purchase"), "fail")
        self.assertEqual(_status(available, "strategic_investors"), "fail")
        self.assertEqual(_status(unavailable, "recent_cluster_purchase"), "unknown")
        self.assertEqual(_status(unavailable, "strategic_investors"), "unknown")


def _status(evaluation, rule_id):
    return next(rule.status for rule in evaluation.rules if rule.id == rule_id)


if __name__ == "__main__":
    unittest.main()
