import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from data_sources.sec_client import _ownership_filings, enrich_with_sec, parse_ownership_xml
from models import CompanyMetrics


FORM_4_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0000000001</rptOwnerCik>
      <rptOwnerName>Director One</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>{date}</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>20</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5100</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


class SECClientTest(unittest.TestCase):
    def test_parses_form_4_purchase_and_holding(self):
        date = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()

        parsed = parse_ownership_xml(FORM_4_XML.replace(b"{date}", date.encode()))

        self.assertEqual(parsed["owner_name"], "Director One")
        self.assertEqual(parsed["shares_owned"], 5_100)
        self.assertEqual(parsed["purchases"][0]["value"], 2_000)
        self.assertEqual(parsed["purchases"][0]["position"], "Director")

    def test_parses_ownership_xml_embedded_in_html(self):
        date = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
        document = b"<html><body>" + FORM_4_XML.replace(b"{date}", date.encode()) + b"</body></html>"

        parsed = parse_ownership_xml(document)

        self.assertEqual(parsed["owner_name"], "Director One")

    def test_builds_recent_ownership_filing_urls(self):
        date = datetime.now(timezone.utc).date().isoformat()
        submissions = {
            "filings": {
                "recent": {
                    "form": ["4", "10-K"],
                    "accessionNumber": ["0001234567-26-000001", "0001234567-26-000002"],
                    "primaryDocument": ["form4.xml", "annual.htm"],
                    "filingDate": [date, date],
                }
            }
        }

        filings = _ownership_filings(submissions, "0001234567")

        self.assertEqual(len(filings), 1)
        self.assertIn("/1234567/000123456726000001/form4.xml", filings[0]["url"])

    @patch("data_sources.sec_client._get_bytes")
    @patch("data_sources.sec_client._get_json")
    def test_enriches_missing_insider_metrics(self, get_json, get_bytes):
        date = (datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat()
        get_json.return_value = {
            "filings": {
                "recent": {
                    "form": ["4"],
                    "accessionNumber": ["0001234567-26-000001"],
                    "primaryDocument": ["form4.xml"],
                    "filingDate": [date],
                }
            }
        }
        get_bytes.return_value = FORM_4_XML.replace(b"{date}", date.encode())

        metrics = enrich_with_sec(
            CompanyMetrics(ticker="TEST", sec_cik="0001234567", shares_outstanding=100_000),
            "Stock Screening Tool test@example.com",
        )

        self.assertAlmostEqual(metrics.insider_ownership, 0.051)
        self.assertTrue(metrics.recent_insider_purchases_available)
        self.assertEqual(len(metrics.recent_insider_purchases), 1)
        self.assertIn("SEC EDGAR supplement used", metrics.source_notes[-1])


if __name__ == "__main__":
    unittest.main()
