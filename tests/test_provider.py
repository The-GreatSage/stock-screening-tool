import sys
import unittest
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.provider import _fmp_api_key, fetch_company_metrics


class ProviderTest(unittest.TestCase):
    @patch.dict(os.environ, {"FMP_API_KEY": "", "FMP_API": "legacy-key"})
    def test_accepts_fmp_api_alias(self):
        self.assertEqual(_fmp_api_key(), "legacy-key")

    @patch("data_sources.provider.fetch_with_yahoo_public", side_effect=RuntimeError("fallback blocked"))
    @patch("data_sources.provider.fetch_with_yfinance", side_effect=RuntimeError("primary blocked"))
    def test_returns_partial_metrics_when_all_live_sources_fail(self, _primary, _fallback):
        metrics = fetch_company_metrics("TEST")

        self.assertEqual(metrics.ticker, "TEST")
        self.assertIsNone(metrics.market_cap)
        self.assertIn("Live market data is temporarily unavailable.", metrics.source_notes)


if __name__ == "__main__":
    unittest.main()
