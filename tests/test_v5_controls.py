"""V5 offline checks for stop/resume, deduplicating sync, and worldwide markets."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import storage
import worker
import google_sheets_sync as sync
import engine
from markets import MARKETS, REGIONS

ROW={'Country':'Canada','City':'Toronto','Business Name':'Example Advisory',
     'Category':'Business Consultants','Website':'', 'Business Email':'', 'Phone':'',
     'OSM Listing':'https://www.openstreetmap.org/node/42'}
SHEET='1abcdefghijklmnopqrstuvwxyz1234567890abcdef'
URL='https://script.google.com/macros/s/AKfycb_test123/exec'
CFG={'cities':['Canada · Toronto','United Kingdom · Leeds'], 'categories':['Business Consultants'],
     'radius':5,'exclude_large':True,'enrich_sites':False,'site_limit':0}

class V5Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=(storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE)
        storage.BASE_DIR=Path(self.temp.name)
        storage.DB_FILE=storage.BASE_DIR/'leads.sqlite3'
        storage.CSV_FILE=storage.BASE_DIR/'leads.csv'
        storage.XLSX_FILE=storage.BASE_DIR/'leads.xlsx'
        storage.init()

    def tearDown(self):
        storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE=self.old
        self.temp.cleanup()

    def test_worldwide_market_data(self):
        self.assertGreaterEqual(len(MARKETS),90)
        self.assertEqual(len(REGIONS),7)
        self.assertNotIn('United Arab Emirates',MARKETS)
        for country,info in MARKETS.items():
            self.assertIn(info['region'],REGIONS)
            self.assertEqual(len(info['country_code']),2)
            for city,latlon in info['cities'].items():
                self.assertTrue(city)
                self.assertTrue(-90<=latlon[0]<=90 and -180<=latlon[1]<=180)

    def test_stop_queued_then_resume(self):
        rid=storage.create_run(CFG)
        self.assertTrue(storage.request_stop_run(rid))
        self.assertEqual(storage.get_run(rid)['status'],'paused')
        self.assertTrue(storage.stop_run_requested(rid))
        self.assertFalse(storage.acquire_worker(rid))
        storage.clear_stop_run(rid)
        self.assertTrue(storage.acquire_worker(rid))

    def test_stop_during_city_then_resume_without_requery(self):
        rid=storage.create_run(CFG)
        invoked=[]
        def fake_discovery(country,city,*args):
            invoked.append((country,city))
            storage.request_stop_run(rid)
            return [{**ROW,'Country':country,'City':city}]
        with patch.object(worker,'query_city',side_effect=fake_discovery):
            worker.process(rid)
        self.assertEqual(storage.get_run(rid)['status'],'paused')
        self.assertEqual(len(invoked),1)
        self.assertEqual(storage.metrics(rid)['pending'],1)
        self.assertEqual(storage.metrics(rid)['finished'],0)
        storage.clear_stop_run(rid)
        def next_discovery(country,city,*args):
            invoked.append((country,city))
            return [{**ROW,'Country':country,'City':city}]
        with patch.object(worker,'query_city',side_effect=next_discovery), \
             patch.object(engine,'email_status',return_value='Missing'):
            worker.process(rid)
        self.assertEqual(storage.get_run(rid)['status'],'complete')
        self.assertEqual(len(invoked),2)
        self.assertEqual(storage.metrics(rid)['finished'],2)
        self.assertEqual(storage.metrics(rid)['pending'],0)

    def test_stop_sync_between_batches(self):
        rid=storage.create_run({'cities':['Canada · Toronto'],'categories':['Business Consultants']})
        for i in range(26):
            storage.save_lead(rid,{**ROW,'Business Name':f'Business {i}'},write_exports=False)
        storage.cloud_choose_sheet(SHEET)
        storage.cloud_connect(URL)
        calls=[]
        def fake_post(url,payload):
            calls.append(payload)
            storage.set_cloud_sync_paused(True)
            return {'ok':True,'version':7,'sheet_id':SHEET,
                    'accepted_ids':[r['id'] for r in payload['rows']],
                    'inserted':len(payload['rows'])}
        with patch.object(sync,'post',side_effect=fake_post):
            result=sync.sync_pending(max_batches=10)
        self.assertEqual(result['sent'],25)
        self.assertTrue(result['paused'])
        self.assertEqual(len(calls),1)
        self.assertEqual(storage.cloud_pending_count(),1)
        with patch.object(sync,'post',side_effect=AssertionError('No Google calls when paused')):
            self.assertTrue(sync.sync_pending()['paused'])
        storage.set_cloud_sync_paused(False)
        with patch.object(sync,'post',return_value={'ok':True,'version':7,'sheet_id':SHEET,
                                                    'accepted_ids':[storage.cloud_pending_rows()[0]['id']],'inserted':1}):
            done=sync.sync_pending()
        self.assertEqual(done['sent'],1)
        self.assertEqual(storage.cloud_pending_count(),0)

    def test_v4_database_migrates_without_losing_runs(self):
        import sqlite3
        with storage._connection() as con:
            # Simulate a user with a pre-V5 schema by dropping the new column.
            con.execute('ALTER TABLE runs DROP COLUMN stop_requested')
            con.execute("INSERT INTO runs(config,status,phase,started_at) VALUES ('{}','partial','Old run','2026-11-01T00:00:00+00:00')")
        storage.init()
        with storage._connection() as con:
            row=con.execute("SELECT phase,stop_requested FROM runs WHERE phase='Old run'").fetchone()
        self.assertEqual(row['stop_requested'],0)
        self.assertEqual(row['phase'],'Old run')

    def test_lease_prevents_second_sync_worker(self):
        token=storage.acquire_sync_lease()
        self.assertIsNotNone(token)
        self.assertIsNone(storage.acquire_sync_lease())
        storage.release_sync_lease(token)
        token2=storage.acquire_sync_lease()
        self.assertIsNotNone(token2)
        storage.release_sync_lease(token2)

if __name__=='__main__':
    unittest.main()

# Above unittest.main guard runs only when invoked directly; discovered methods below
# are added to the class for a backwards compatibility migration fixture.
