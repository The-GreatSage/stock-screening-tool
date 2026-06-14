import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.yfinance_client import _latest_from_rows, _major_holder_value, _percent_to_ratio, _sum_latest


class Row:
    def __init__(self, value):
        self.iloc = [value]


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


if __name__ == "__main__":
    unittest.main()
