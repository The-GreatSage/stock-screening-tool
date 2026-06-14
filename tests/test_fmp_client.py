import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.fmp_client import (
    FMPResponse,
    _estimated_insider_ownership,
    _recent_insider_purchases,
    enrich_with_fmp,
)
from models import CompanyMetrics
from unittest.mock import patch


class FMPClientTest(unittest.TestCase):
    def test_estimates_ownership_from_latest_record_per_insider(self):
        records = [
            {"reportingCik": "1", "securityName": "Common Stock", "securitiesOwned": 600},
            {"reportingCik": "1", "securityName": "Common Stock", "securitiesOwned": 500},
            {"reportingCik": "2", "securityName": "Common Shares", "securitiesOwned": 200},
        ]

        ownership = _estimated_insider_ownership(records, 10_000)

        self.assertAlmostEqual(ownership, 0.08)

    def test_extracts_recent_open_market_purchases(self):
        recent = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
        records = [
            {
                "reportingName": "Director One",
                "typeOfOwner": "Director",
                "transactionDate": recent,
                "acquisitionOrDisposition": "A",
                "transactionType": "P-Purchase",
                "securitiesTransacted": 100,
                "price": 20,
            }
        ]

        purchases, available = _recent_insider_purchases(records, True)

        self.assertTrue(available)
        self.assertEqual(len(purchases), 1)
        self.assertEqual(purchases[0]["value"], 2_000)

    @patch("data_sources.fmp_client._get", return_value=FMPResponse())
    def test_notes_when_key_is_configured_but_endpoints_are_unavailable(self, _get):
        metrics = enrich_with_fmp(CompanyMetrics(ticker="TEST"), "secret")

        self.assertIn("FMP_API_KEY is configured", metrics.source_notes[-1])

    @patch("data_sources.fmp_client._get")
    def test_normalizes_profile_cik(self, _get):
        _get.side_effect = lambda path, _params, _key: (
            FMPResponse([{"cik": "320193"}], True) if path == "profile" else FMPResponse()
        )
        metrics = enrich_with_fmp(CompanyMetrics(ticker="AAPL"), "secret")

        self.assertEqual(metrics.sec_cik, "0000320193")


if __name__ == "__main__":
    unittest.main()
