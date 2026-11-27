import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality
import storage
import research_worker
import engine

BASE = {'Country':'Germany','City':'Berlin','Business Name':'Example Accounting',
        'Category':'Accounting Firms','Business Email':'','Phone':'','Website':''}

class QualityTests(unittest.TestCase):
    def test_all_eight_contact_categories(self):
        for inputs, (code,_) in quality.CODES.items():
            website,email,phone=inputs
            row={**BASE,'Website':'https://example.org' if website else '',
                 'Business Email':'info@example.org' if email else '',
                 'Phone':'+493012345678' if phone else ''}
            got=quality.classify(row)
            self.assertTrue(got['Contact Category'].startswith(code+' '),got)
            if code=='C1':
                self.assertEqual(got['Workflow Queue'],'Needs Contact Research')
            if code=='D':
                self.assertEqual(got['Workflow Queue'],'Hold')
            if code in ('A1','A2','A3','B1','B2','B3'):
                self.assertEqual(got['Workflow Queue'],'Ready for Outreach')

    def test_fit_separate_from_contact_completeness(self):
        result=quality.classify({**BASE,'Website':'https://example.org',
            'Phone':'+493012345678','Business Email':'info@example.org'})
        self.assertEqual(result['Contact Category'],'A1 – Complete')
        self.assertEqual(result['Partnership Fit'],'Medium')
        self.assertNotEqual(result['Contact Verification'],'Official website source match (not active verified)')
        large=quality.classify({**BASE,'Business Name':'Deloitte Berlin',
                                'Business Email':'info@deloitte.example'})
        self.assertEqual(large['Partnership Fit'],'Low')
        self.assertEqual(large['Workflow Queue'],'Hold')

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=(storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE)
        storage.BASE_DIR=Path(self.temp.name)
        storage.DB_FILE=storage.BASE_DIR/'partner_leads.sqlite3'
        storage.CSV_FILE=storage.BASE_DIR/'partner_leads_live.csv'
        storage.XLSX_FILE=storage.BASE_DIR/'partner_leads_live.xlsx'
        storage.init()
    def tearDown(self):
        storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE=self.old
        self.temp.cleanup()

    def test_research_enriches_existing_id(self):
        rid=storage.create_run({'cities':['Germany · Berlin'],'categories':['Accounting Firms']})
        row={**BASE,'Website':'https://example.org','OSM Listing':'https://www.openstreetmap.org/node/9'}
        storage.save_discovery(rid,'Germany','Berlin',[row]); storage.save_lead(rid,row)
        key=storage.key_for(row)
        self.assertEqual(storage.queue_research(limit=5),1)
        def research(rows, **kwargs):
            return [quality.classify({**rows[0],'Business Email':'info@example.org',
                                      'Email Source':'Official website public page'})]
        with patch.object(research_worker,'refine',side_effect=research):
            research_worker.run()
        self.assertEqual(storage.all_leads()[0]['Business Email'],'info@example.org')
        self.assertEqual(storage.all_leads()[0]['Contact Category'].split()[0],'A2')
        self.assertEqual(storage.research_status()['done'],1)
        self.assertEqual(storage.cloud_pending_rows()[0]['id'],key)

if __name__=='__main__': unittest.main()
