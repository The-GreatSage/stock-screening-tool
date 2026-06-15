import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.performance_client import _normalize_points, select_benchmarks


class PerformanceClientTest(unittest.TestCase):
    def test_selects_mining_benchmarks_from_industry(self):
        benchmarks, rationale = select_benchmarks("Basic Materials", "Gold Mining")

        self.assertEqual([item[0] for item in benchmarks], ["XME", "GDX"])
        self.assertIn("Mining", rationale)

    def test_selects_technology_benchmarks(self):
        benchmarks, _ = select_benchmarks("Technology", "Consumer Electronics")

        self.assertEqual([item[0] for item in benchmarks], ["QQQ", "SPY"])

    def test_normalizes_performance_to_first_valid_value(self):
        points = _normalize_points(
            [datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3)],
            [100, 110, 90],
        )

        self.assertEqual(points[0]["value"], 0)
        self.assertAlmostEqual(points[1]["value"], 10)
        self.assertAlmostEqual(points[2]["value"], -10)


if __name__ == "__main__":
    unittest.main()
