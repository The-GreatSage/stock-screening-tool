import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.yfinance_client import _major_holder_value


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


if __name__ == "__main__":
    unittest.main()
