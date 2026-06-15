import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.yfinance_client import (
    _latest_from_rows,
    _major_holder_value,
    _percent_to_ratio,
    _quarterly_reports,
    _recent_earnings_reports,
    _recent_news,
    _sum_latest,
)


class Row:
    def __init__(self, value):
        self.iloc = [value]


class EarningsFrame:
    empty = False

    def iterrows(self):
        return iter(
            [
                (
                    "2026-05-01T16:00:00-04:00",
                    {"EPS Estimate": 1.50, "Reported EPS": 1.65, "Surprise(%)": 10.0},
                ),
                (
                    "2026-02-01T16:00:00-05:00",
                    {"EPS Estimate": 1.20, "Reported EPS": 1.18, "Surprise(%)": -1.7},
                ),
                (
                    "2026-08-01T16:00:00-04:00",
                    {"EPS Estimate": 1.80, "Reported EPS": None, "Surprise(%)": None},
                ),
            ]
        )


class QuarterlyFrame:
    empty = False
    columns = ["2026-03-31", "2025-12-31", "2025-09-30"]
    index = ["Total Revenue", "Net Income", "Diluted EPS"]
    loc = {
        ("Total Revenue", "2026-03-31"): 600_000_000,
        ("Net Income", "2026-03-31"): 120_000_000,
        ("Diluted EPS", "2026-03-31"): 1.2,
        ("Total Revenue", "2025-12-31"): 550_000_000,
        ("Net Income", "2025-12-31"): 110_000_000,
        ("Diluted EPS", "2025-12-31"): 1.1,
        ("Total Revenue", "2025-09-30"): 500_000_000,
        ("Net Income", "2025-09-30"): 100_000_000,
        ("Diluted EPS", "2025-09-30"): 1.0,
    }


class YFinanceClientTest(unittest.TestCase):
    def test_reads_insider_ownership_from_major_holders(self):
        class TestFrame:
            index = ["insidersPercentHeld"]

            @property
            def loc(self):
                return {"insidersPercentHeld": Row(0.081)}

        self.assertEqual(_major_holder_value((TestFrame(), True), "insidersPercentHeld"), 0.081)

    def test_sums_exactly_four_latest_quarters(self):
        self.assertAlmostEqual(_sum_latest([0.16, 0.20, 0.23, 0.20, 0.20], 4), 0.79)
        self.assertIsNone(_sum_latest([0.16, 0.20, 0.23], 4))

    def test_normalizes_yahoo_percentage_ratio(self):
        self.assertAlmostEqual(_percent_to_ratio(0.264), 0.00264)
        self.assertAlmostEqual(_percent_to_ratio(79.548), 0.79548)

    def test_uses_financial_company_cash_row_fallback(self):
        cash = _latest_from_rows(
            {"Cash Cash Equivalents And Federal Funds Sold": [3_761_251_000]},
            "Cash Cash Equivalents And Short Term Investments",
            "Cash Cash Equivalents And Federal Funds Sold",
            "Cash And Cash Equivalents",
        )

        self.assertEqual(cash, 3_761_251_000)

    def test_normalizes_recent_news(self):
        news = _recent_news(
            [
                {
                    "content": {
                        "title": "Company launches a new product",
                        "provider": {"displayName": "Reuters"},
                        "pubDate": "2026-06-14T12:00:00Z",
                        "canonicalUrl": {"url": "https://example.com/news"},
                    }
                }
            ]
        )

        self.assertEqual(news[0]["publisher"], "Reuters")
        self.assertEqual(news[0]["published"], "2026-06-14")
        self.assertEqual(news[0]["url"], "https://example.com/news")

    def test_keeps_latest_completed_earnings_reports(self):
        reports = _recent_earnings_reports(EarningsFrame())

        self.assertEqual(len(reports), 2)
        self.assertEqual(reports[0]["date"], "2026-05-01")
        self.assertEqual(reports[0]["reported_eps"], 1.65)

    def test_builds_earnings_report_fallback_from_quarterly_statements(self):
        reports = _quarterly_reports(QuarterlyFrame())

        self.assertEqual(len(reports), 3)
        self.assertEqual(reports[0]["date"], "2026-03-31")
        self.assertEqual(reports[0]["net_income"], 120_000_000)


if __name__ == "__main__":
    unittest.main()
