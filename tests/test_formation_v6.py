"""V6 formation-only classification and migration regression checks."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine
import storage
from formation_filter import (CATEGORY, LEGACY_CATEGORY, website_evidence,
                              map_evidence, clearly_other_consultancy)
from quality import classify

BASE = dict(Country='Germany', City='Berlin', Category=CATEGORY,
            Website='https://example.org', Phone='+49 30 12345678',
            **{'Business Email':'hello@example.org',
               'OSM Listing':'https://www.openstreetmap.org/node/15'})

class ServiceRelevanceTests(unittest.TestCase):
    def test_specific_terms_across_languages(self):
        for text in ('Company Formation Services', 'Business Setup Consultants',
                     'Company incorporation', 'Firmengründung', 'Création d’entreprise',
                     'Constitución de sociedades', 'Bedrijf oprichten',
                     'تأسيس الشركات', '公司注册'):
            self.assertTrue(website_evidence(text), text)

    def test_generic_and_unrelated_terms_do_not_qualify(self):
        for text in ('Management consultants and business strategy',
                     'IT consultancy', 'Marketing advisory',
                     'Company registration number 12345678',
                     'Corporate finance and M&A', 'Business coaching'):
            self.assertEqual(website_evidence(text), '', text)
        self.assertTrue(clearly_other_consultancy('XYZ Digital Marketing Consulting'))
        self.assertFalse(clearly_other_consultancy('XYZ IT and Company Formation'))

    def test_osm_generic_office_tag_not_evidence(self):
        self.assertEqual(map_evidence('ABC Consulting', {'office':'consulting'}), '')
        self.assertTrue(map_evidence('ABC Consulting', {'office':'consulting',
                                                      'description':'Company incorporation services'}))

    def test_filter_skips_unrelated_consultant_even_with_contact(self):
        row = {**BASE, 'Business Name':'Alpha Management Consulting'}
        excluded=[]
        with patch.object(engine, 'site_enrichment', side_effect=AssertionError('should skip before web')):
            result = engine.refine([row], max_websites=1, on_skip=excluded.append)
        self.assertEqual(result, [])
        self.assertEqual(excluded[0]['Business Name'],row['Business Name'])

    def test_generic_without_specific_site_evidence_is_excluded(self):
        row = {**BASE, 'Business Name':'Local Consultancy'}
        site = dict(emails=[], phones=[], pages=['https://example.org'],
                    uae_mention='Not found in checked pages',size_hint='',
                    formation_phrase='',formation_url='')
        with patch.object(engine,'site_enrichment',return_value=site):
            self.assertEqual(engine.refine([row],1), [])

    def test_official_website_service_evidence_allows_outreach(self):
        row = {**BASE,'Business Name':'Silver Consultancy'}
        site = dict(emails=[],phones=[],pages=['https://example.org/setup'],
                    uae_mention='Not found in checked pages',size_hint='',
                    formation_phrase='company incorporation', formation_url='https://example.org/setup')
        with patch.object(engine,'site_enrichment',return_value=site), \
             patch.object(engine,'email_status',return_value='Valid syntax + MX (delivery NOT verified)'), \
             patch.object(engine,'normalized_phone',return_value=('+493012345678','Valid numbering format (NOT active-line verified)')):
            output=engine.refine([row],1)
        self.assertEqual(len(output),1)
        self.assertEqual(output[0]['Category'],CATEGORY)
        self.assertEqual(output[0]['Service Qualification'],'Website evidence')
        self.assertEqual(output[0]['Workflow Queue'],'Ready for Outreach')
        self.assertIn('https://example.org/setup',output[0]['Fit Evidence'])

    def test_osm_name_only_is_not_ready_for_outreach(self):
        row = {**BASE,'Business Name':'Bluebird Company Formation', 'Website':''}
        with patch.object(engine,'email_status',return_value='Valid syntax + MX (delivery NOT verified)'), \
             patch.object(engine,'normalized_phone',return_value=('+493012345678','Valid numbering format (NOT active-line verified)')):
            output=engine.refine([row],0)
        self.assertEqual(len(output),1)
        self.assertEqual(output[0]['Workflow Queue'],'Needs Service Verification')
        self.assertEqual(output[0]['Partnership Fit'],'Unknown')

    def test_website_service_link_prioritized(self):
        home = SimpleNamespace(content=b'''<html><body><a href="/services/company-formation">Company Formation</a>
        <a href="mailto:contact@example.org">Email</a></body></html>''')
        service = SimpleNamespace(content=b'<html><body>We provide company incorporation services.</body></html>')
        def get(url):
            if url.endswith('/services/company-formation'):
                return service
            if url == 'https://example.org':
                return home
            return None
        with patch.object(engine,'_can_fetch',return_value=(True,0)), \
             patch.object(engine,'_get_public',side_effect=get), \
             patch.object(engine,'_public_hostname',return_value=True):
            result=engine.site_enrichment('https://example.org',check_formation=True)
        self.assertIn('company formation',result['formation_phrase'])
        self.assertIn('contact@example.org',result['emails'])

    def test_legacy_leads_remain_but_not_outreach(self):
        row={**BASE,'Business Name':'Legacy Generic Consulting','Category':LEGACY_CATEGORY}
        old=classify(row)
        self.assertEqual(old['Workflow Queue'],'Needs Service Verification')
        self.assertEqual(old['Partnership Fit'],'Unknown')

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=(storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE)
        storage.BASE_DIR=Path(self.tmp.name)
        storage.DB_FILE=storage.BASE_DIR/'leads.sqlite3'
        storage.CSV_FILE=storage.BASE_DIR/'leads.csv'
        storage.XLSX_FILE=storage.BASE_DIR/'leads.xlsx'
        storage.init()
    def tearDown(self):
        storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE=self.old
        self.tmp.cleanup()
    def test_legacy_record_upgrade_keeps_lead_id(self):
        run_id=storage.create_run({'cities':['Germany · Berlin'],'categories':[LEGACY_CATEGORY]})
        old_row={**BASE,'Business Name':'Acme Company Formation','Category':LEGACY_CATEGORY}
        storage.save_discovery(run_id,'Germany','Berlin',[old_row])
        storage.save_lead(run_id,old_row)
        lead_id=storage.key_for(old_row)
        self.assertEqual(storage.cloud_pending_rows()[0]['id'],lead_id)
        new_row=dict(old_row,Category=CATEGORY, **{
            'Service Qualification':'Website evidence', 'Service Evidence':'company incorporation · https://example.org'})
        storage.update_existing_lead(lead_id,new_row)
        self.assertEqual(storage.cloud_pending_rows()[0]['id'],lead_id)
        self.assertEqual(storage.all_leads()[0]['Category'],CATEGORY)
        self.assertEqual(storage.all_leads()[0]['Workflow Queue'],'Ready for Outreach')

if __name__ == '__main__': unittest.main()
