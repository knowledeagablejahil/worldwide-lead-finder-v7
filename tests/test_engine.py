import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
from engine import build_query, normalize_url, first_email, is_large_chain, deduplicate, csv_bytes, normalized_phone

class EngineTests(unittest.TestCase):
    def test_query(self):
        q = build_query(51.5074, -0.1278, 8, ["Accounting Firms", "Law Firms"])
        self.assertIn('"office"~', q)
        self.assertIn('accountant', q)
        self.assertIn('lawyer', q)
        self.assertIn('around:8000', q)

    def test_url_email(self):
        self.assertEqual(normalize_url("example.org"), "https://example.org")
        self.assertEqual(first_email("Contact INFO@example.org now"), "info@example.org")

    def test_brand_filter(self):
        self.assertTrue(is_large_chain("KPMG London"))
        self.assertFalse(is_large_chain("Bright Ideas Legal Limited"))

    def test_dedupe(self):
        rows = [
            {"Country": "Germany", "City": "Berlin", "Business Name": "Acme Advisory", "Website": "", "Phone": "", "Business Email": ""},
            {"Country": "Germany", "City": "Berlin", "Business Name": "ACME Advisory", "Website": "https://acme.example", "Phone": "", "Business Email": ""},
        ]
        self.assertEqual(len(deduplicate(rows)), 1)
        self.assertTrue(deduplicate(rows)[0]["Website"])

    def test_phone(self):
        number, status = normalized_phone("+44 20 7946 0958", "GB")
        self.assertTrue(number.startswith("+44"))
        self.assertTrue("numbering" in status.lower() or "invalid" in status.lower() or "unavailable" in status.lower())

    def test_overpass_fixture_parsing(self):
        from unittest.mock import patch
        payload = {"elements": [{"type": "node", "id": 1234,
                 "tags": {"name": "Berlin Accountancy", "office": "accountant",
                          "website": "berlin-example.de", "phone": "+49 30 12345"}}]}
        with patch.object(engine, "_safe_cache_read", return_value=payload):
            data = engine.query_city("Germany", "Berlin", 7, ["Accounting Firms"])
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["Website"], "https://berlin-example.de")
        self.assertEqual(data[0]["OSM Listing"], "https://www.openstreetmap.org/node/1234")

    def test_refine_with_mock_contacts(self):
        from unittest.mock import patch
        row = {
            "Country": "Germany", "City": "Berlin", "Business Name": "Local Advisory",
            "Category": "Business Consultants", "Website": "https://local.example",
            "Business Email": "", "Phone": "", "OSM Listing": "https://www.openstreetmap.org/node/1",
        }
        site = {"emails": ["info@local.example"], "phones": ["+49 30 12345678"],
                "pages": ["https://local.example/contact"], "uae_mention": "Not found in checked pages",
                "size_hint": "Smaller-firm wording on website (unverified)"}
        with patch.object(engine, "site_enrichment", return_value=site), \
             patch.object(engine, "email_status", return_value="Valid syntax + MX (delivery NOT verified)"), \
             patch.object(engine, "normalized_phone", return_value=("+493012345678", "Valid numbering format (NOT active-line verified)")):
            result = engine.refine([row], 1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["Business Email"], "info@local.example")
        self.assertIn("listed website", result[0]["Phone Website Match"])
        # Legacy generic consultants stay saved but must be service-verified.
        self.assertEqual(result[0]["Partnership Priority"], "Pending service verification")
        self.assertEqual(result[0]["Workflow Queue"], "Needs Service Verification")

    def test_csv_escape(self):
        txt = csv_bytes([{"Business Name": "=1+1", "Phone": "+442079460000"}]).decode("utf-8-sig")
        self.assertIn("'=1+1", txt)
        self.assertIn("'+442079460000", txt)

if __name__ == "__main__":
    unittest.main()
