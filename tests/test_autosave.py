"""Offline test: saved leads survive restarts; Excel/CSV rebuild from SQLite."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP_ROOT = tempfile.TemporaryDirectory()
os.environ['PARTNER_FINDER_DATA_DIR'] = TMP_ROOT.name
import engine
import storage
import worker

ROW = {
    'Country': 'Germany', 'City': 'Berlin', 'Business Name': 'Example & Sons',
    'Category': 'Accounting Firms', 'Website': 'https://example.org',
    'Business Email': 'info@example.org', 'Email Source': 'OpenStreetMap',
    'Phone': '+49 30 123456', 'OSM Listing': 'https://www.openstreetmap.org/node/1'
}

class AutosaveTests(unittest.TestCase):
    def setUp(self):
        storage.init()

    def test_db_autoexport_and_reload(self):
        cfg = {'cities': ['Germany · Berlin'], 'categories': ['Accounting Firms'],
               'radius': 8,'exclude_large': True,'enrich_sites': False,'site_limit':0}
        rid = storage.create_run(cfg)
        storage.save_discovery(rid, 'Germany', 'Berlin', [ROW])
        self.assertEqual(len(storage.pending_rows(rid)),1)
        self.assertTrue(storage.acquire_worker(rid))
        self.assertFalse(storage.acquire_worker(rid))
        enriched = {**ROW, 'Score': 45, 'Partnership Priority':'Medium'}
        storage.save_lead(rid,enriched)
        self.assertEqual(storage.metrics(rid)['finished'],1)
        self.assertEqual(storage.metrics(rid)['pending'],0)
        self.assertEqual(storage.all_leads()[-1]['Business Name'],'Example & Sons')
        self.assertIn('Example & Sons',storage.CSV_FILE.read_text('utf-8-sig'))
        with zipfile.ZipFile(storage.XLSX_FILE) as z:
            self.assertIsNone(z.testzip())
            root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            ns={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(len(root.findall('.//x:sheetData/x:row',ns)),2)
            self.assertIn('Example &amp; Sons',z.read('xl/worksheets/sheet1.xml').decode())
        # Simulate closing and restarting Python; database and CSV stay readable
        with storage._connection() as conn:
            saved=conn.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
        self.assertGreaterEqual(saved,1)

    def test_resume_unfinished_processed_once(self):
        cfg = {'cities': ['United Kingdom · Manchester'], 'categories': ['Law Firms'],
               'radius': 7,'exclude_large': True,'enrich_sites': False,'site_limit':0}
        rid = storage.create_run(cfg)
        rows = [{**ROW,'Country':'United Kingdom','City':'Manchester','Business Name':'Adam Legal',
                 'Website':''},{**ROW,'Country':'United Kingdom','City':'Manchester','Business Name':'Beta Legal',
                 'Website':''}]
        with patch.object(worker,'query_city',return_value=rows), \
             patch.object(engine,'email_status',return_value='Valid syntax + MX (delivery NOT verified)'), \
             patch.object(engine,'normalized_phone',return_value=('+442079460000','Valid numbering format (NOT active-line verified)')):
            worker.process(rid)
        self.assertEqual(storage.get_run(rid)['status'], 'complete')
        self.assertEqual(storage.metrics(rid)['finished'], 2)
        self.assertEqual(storage.metrics(rid)['pending'], 0)
        self.assertFalse(storage.acquire_worker(rid))

if __name__ == '__main__':
    unittest.main()
