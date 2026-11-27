"""No Google credentials or internet needed: tests persistence and protocol."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import google_sheets_sync as sync
import storage

ROW = {'Country':'Germany','City':'Hamburg','Business Name':'Local & Partner',
       'Category':'Law Firms','Business Email':'info@example.com',
       'Phone':'+49 40 12345', 'Score':80}
FAKE_SHEET = '1Abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG'
FAKE_EXEC = 'https://script.google.com/macros/s/AKfycb_test123/exec'

class GoogleSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = (storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE)
        storage.BASE_DIR = Path(self.temp.name)
        storage.DB_FILE = storage.BASE_DIR/'partner_leads.sqlite3'
        storage.CSV_FILE = storage.BASE_DIR/'partner_leads_live.csv'
        storage.XLSX_FILE = storage.BASE_DIR/'partner_leads_live.xlsx'
        storage.init()

    def tearDown(self):
        storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE = self.old
        self.temp.cleanup()

    def seed(self):
        rid = storage.create_run({'cities':['Germany · Hamburg'], 'categories':['Law Firms']})
        storage.save_discovery(rid,'Germany','Hamburg',[ROW])
        storage.save_lead(rid, ROW)
        return rid

    def test_google_code_and_url_validators(self):
        self.assertEqual(sync.extract_sheet_id('https://docs.google.com/spreadsheets/d/'+FAKE_SHEET+'/edit#gid=4'),FAKE_SHEET)
        self.assertEqual(sync.validate_script_url(FAKE_EXEC),FAKE_EXEC)
        for bad in ['http://script.google.com/macros/s/abc/exec',
                    'https://evil.com/macros/s/abc/exec',
                    'https://script.google.com/macros/s/abc/dev']:
            with self.assertRaises(ValueError):
                sync.validate_script_url(bad)
        settings = storage.cloud_settings()
        code = sync.script_code(FAKE_SHEET, settings['secret'])
        self.assertIn(FAKE_SHEET, code)
        self.assertIn(settings['secret'], code)
        self.assertNotIn('__SHEET_ID__', code)

    def test_existing_v2_lead_uploads_once_and_retries(self):
        self.seed()
        storage.cloud_choose_sheet(FAKE_SHEET)
        cfg = storage.cloud_settings()
        self.assertGreaterEqual(len(cfg['secret']),28)
        self.assertEqual(storage.cloud_pending_count(),1)
        storage.cloud_connect(FAKE_EXEC)
        sent = []
        def fake_post(_url, payload):
            assert payload['secret'] == cfg['secret']
            assert payload['action'] == 'upsert'
            sent.extend(payload['rows'])
            return {'ok':True,'accepted_ids':[x['id'] for x in payload['rows']],
                    'inserted':len(payload['rows']),'sheet_id':FAKE_SHEET,'version':7}
        with patch.object(sync,'post',side_effect=fake_post):
            result=sync.sync_pending()
        self.assertEqual(result['sent'],1)
        self.assertEqual(storage.cloud_pending_count(),0)
        self.assertEqual(storage.cloud_synced_count(),1)
        self.assertEqual(len(sent),1)
        with patch.object(sync,'post',side_effect=fake_post):
            again=sync.sync_pending()
        self.assertEqual(again['sent'],0)
        self.assertEqual(len(sent),1)

    def test_existing_google_row_gets_updated_without_new_id(self):
        self.seed()
        storage.cloud_choose_sheet(FAKE_SHEET)
        storage.cloud_connect(FAKE_EXEC)
        sent = []
        def fake_post(_url,payload):
            sent.append(payload['rows'])
            return {'ok':True,'version':7,'accepted_ids':[x['id'] for x in payload['rows']],
                    'sheet_id':FAKE_SHEET,'inserted':0,'updated':len(payload['rows'])}
        with patch.object(sync,'post',side_effect=fake_post):
            self.assertEqual(sync.sync_pending()['sent'],1)
        before=sent[0][0]['id']
        row=storage.all_leads()[0]
        row['Website']='https://example.com'
        storage.update_existing_lead(before,row)
        self.assertEqual(storage.cloud_pending_count(),1)
        with patch.object(sync,'post',side_effect=fake_post):
            self.assertEqual(sync.sync_pending()['sent'],1)
        self.assertEqual(sent[1][0]['id'],before)
        self.assertEqual(sent[1][0]['data']['Contact Category'].split()[0],'A1')
        self.assertEqual(storage.cloud_pending_count(),0)

    def test_old_receiver_cannot_falsely_ack_updates(self):
        self.seed()
        storage.cloud_choose_sheet(FAKE_SHEET)
        storage.cloud_connect(FAKE_EXEC)
        with patch.object(sync,'post',return_value={'ok':True,'accepted_ids':[storage.cloud_pending_rows()[0]['id']],
                                                    'sheet_id':FAKE_SHEET}):
            result=sync.sync_pending()
        self.assertEqual(result['sent'],0)
        self.assertEqual(result['pending'],1)
        self.assertIn('V7',result['error'])

    def test_failed_cloud_call_preserves_pending(self):
        self.seed()
        storage.cloud_choose_sheet(FAKE_SHEET)
        storage.cloud_connect(FAKE_EXEC)
        with patch.object(sync,'post',side_effect=RuntimeError('Network offline')):
            result=sync.sync_pending()
        self.assertEqual(result['pending'],1)
        self.assertEqual(storage.cloud_synced_count(),0)
        self.assertIn('Network offline',storage.cloud_settings()['sync_message'])
        self.assertEqual(len(storage.all_leads()),1)

    def test_new_sheet_resends_saved_history(self):
        self.seed()
        storage.cloud_choose_sheet(FAKE_SHEET)
        first = storage.cloud_pending_rows()[0]
        storage.cloud_mark_synced([(first['id'],first['hash'])])
        self.assertEqual(storage.cloud_pending_count(),0)
        storage.cloud_choose_sheet('1Qwertyuiopasdfghjklzxcvbnm123456789ABC')
        self.assertEqual(storage.cloud_pending_count(),1)
        self.assertEqual(storage.cloud_settings()['script_url'],'')

if __name__=='__main__':
    unittest.main()
