import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.market_client import _fetch_market, _quote_from_closes


class FastInfoTicker:
    fast_info = {"lastPrice": 5200, "previousClose": 5150}


class FakeYFinance:
    @staticmethod
    def Ticker(_symbol):
        return FastInfoTicker()


class MarketClientTest(unittest.TestCase):
    def test_calculates_market_change(self):
        quote = _fetch_market(FakeYFinance(), "^GSPC", "S&P 500")

        self.assertEqual(quote["price"], 5200)
        self.assertEqual(quote["change"], 50)
        self.assertAlmostEqual(quote["change_percent"], 50 / 5150)

    def test_builds_quote_from_non_empty_historical_closes(self):
        quote = _quote_from_closes("^VIX", "VIX", [None, 20.0, float("nan"), 18.0])

        self.assertEqual(quote["price"], 18.0)
        self.assertEqual(quote["change"], -2.0)
        self.assertEqual(quote["change_percent"], -0.1)


if __name__ == "__main__":
    unittest.main()
