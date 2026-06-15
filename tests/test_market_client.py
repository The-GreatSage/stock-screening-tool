import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.market_client import _fetch_market


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


if __name__ == "__main__":
    unittest.main()
