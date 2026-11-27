"""V7 company LinkedIn search, cautious match status and migration tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import linkedin_discovery as li
import engine, storage, google_sheets_sync

ROW={'Country':'Germany','City':'Berlin','Business Name':'Silver Bridge Corporate Services',
     'Category':'Accounting Firms','Website':'https://silverbridge.de','Business Email':'',
     'Phone':'','OSM Listing':'https://www.openstreetmap.org/node/42'}

class LinkTests(unittest.TestCase):
    def test_canonical_company_url_no_personal_profiles(self):
        self.assertEqual(li.company_url('http://linkedin.com/company/SILVER-BRIDGE/?trk=foo'),
                         'https://www.linkedin.com/company/silver-bridge/')
        for bad in ('https://linkedin.com/in/john','https://notlinkedin.com/company/abc',
                    'https://linkedin.com/company/search','https://linkedin.com/company/ab/people',
                    'javascript:alert(1)'):
            self.assertEqual(li.company_url(bad),'',bad)

    def test_independent_public_web_search_not_just_site(self):
        results=[{'url':'https://linkedin.com/company/silver-bridge-corporate-services/',
                  'title':'Silver Bridge Corporate Services | LinkedIn',
                  'description':'Berlin, Germany. Company registration firm'}]
        with patch.object(li,'_bing',return_value=results) as bing:
            out=li.search_company(ROW,site_links=[])
        self.assertTrue(bing.called)
        self.assertEqual(out['LinkedIn Match Status'],'Strong indexed match — review')
        self.assertEqual(out['LinkedIn Search Provider'],'Bing RSS search')
        self.assertTrue(out['LinkedIn Company Page'].startswith('https://www.linkedin.com/company/'))

    def test_only_company_pages_and_bad_name_rejected(self):
        results=[{'url':'https://linkedin.com/in/silver-bridge','title':'Silver Bridge', 'description':'Berlin'},
                 {'url':'https://linkedin.com/company/other-business/','title':'Other Business | LinkedIn','description':'Berlin'}]
        with patch.object(li,'_bing',return_value=results):
            out=li.search_company(ROW)
        self.assertEqual(out['LinkedIn Company Page'],'')
        self.assertEqual(out['LinkedIn Match Status'],'Not found')

    def test_search_failure_is_not_fake_success(self):
        with patch.object(li,'_bing',side_effect=RuntimeError('rate-limited')):
            out=li.search_company(ROW)
        self.assertEqual(out['LinkedIn Match Status'],'Search unavailable')
        self.assertFalse(out['LinkedIn Company Page'])

    def test_official_site_and_index_agree(self):
        url='https://www.linkedin.com/company/silver-bridge-corporate-services/'
        with patch.object(li,'_bing',return_value=[{'url':url,'title':'Silver Bridge Corporate Services','description':'Berlin Germany'}]):
            out=li.search_company(ROW,site_links=[url])
        self.assertEqual(out['LinkedIn Match Status'],'Official website + indexed search match')

    def test_api_provider_optional_without_website(self):
        row=dict(ROW,Website='')
        with patch.object(li,'_brave',return_value=[{'url':'https://linkedin.com/company/silver-bridge-corporate-services',
                                                 'title':row['Business Name'],'description':'Berlin'}]) as mock:
            out=li.search_company(row,api_key='testapikey')
        self.assertTrue(mock.called)
        self.assertEqual(out['LinkedIn Search Provider'],'Brave Search API')
        self.assertIn('/company/',out['LinkedIn Company Page'])

    def test_bing_rss_parsing(self):
        class Response:
            content=b'<rss version="2.0"><channel><item><title>Silver Bridge</title><link>https://linkedin.com/company/silver-bridge/</link><description>Berlin</description></item></channel></rss>'
            def raise_for_status(self):pass
        with patch.object(li.requests,'get',return_value=Response()),patch.object(li,'_throttle'):
            result=li._bing('test query')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['title'],'Silver Bridge')

    def test_refine_new_leads_invokes_independent_search(self):
        def fake_site(*_,**__):
            return dict(emails=[],phones=[],pages=[],size_hint='',uae_mention='Not checked',
                        formation_phrase='',formation_url='',linkedin_links=[])
        lead=dict(ROW)
        with patch.object(engine,'site_enrichment',side_effect=fake_site),\
             patch.object(engine,'email_status',return_value='Missing'),\
             patch.object(engine,'normalized_phone',return_value=('','Missing')),\
             patch.object(engine,'search_company',return_value={
                'LinkedIn Company Page':'https://www.linkedin.com/company/silver-bridge/',
                'LinkedIn Match Status':'Possible company match — review'}) as mock:
            out=engine.refine([lead],max_websites=1,linkedin_search_limit=1)
        self.assertTrue(mock.called)
        self.assertEqual(out[0]['LinkedIn Match Status'],'Possible company match — review')

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=(storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE)
        storage.BASE_DIR=Path(self.tmp.name)
        storage.DB_FILE=storage.BASE_DIR/'data.sqlite3'
        storage.CSV_FILE=storage.BASE_DIR/'data.csv'
        storage.XLSX_FILE=storage.BASE_DIR/'data.xlsx'
        storage.init()
    def tearDown(self):
        storage.BASE_DIR,storage.DB_FILE,storage.CSV_FILE,storage.XLSX_FILE=self.old
        self.tmp.cleanup()
    def test_prior_lead_id_kept_and_only_updates_existing_row(self):
        run=storage.create_run({'cities':['Germany · Berlin'],'categories':['Accounting Firms']})
        storage.save_lead(run,ROW)
        key=storage.key_for(ROW)
        self.assertEqual(storage.linkedin_candidates(),[key])
        self.assertEqual(storage.queue_linkedin(limit=5),1)
        self.assertEqual(storage.pending_linkedin()[0]['lead_key'],key)
        updated=dict(ROW,**{'LinkedIn Company Page':'https://www.linkedin.com/company/silver-bridge/',
                             'LinkedIn Match Status':'Strong indexed match — review',
                             'LinkedIn Search Provider':'Bing RSS search'})
        storage.update_existing_lead(key,updated)
        storage.finish_linkedin(key)
        self.assertEqual(len(storage.all_leads()),1)
        self.assertEqual(storage.linkedin_candidates(),[])
        self.assertEqual(storage.cloud_pending_rows()[0]['id'],key)
        self.assertIn('LinkedIn Company Page',engine.EXPORT_COLUMNS)
        self.assertIn('LinkedIn Company Page',google_sheets_sync.TEMPLATE.read_text())
    def test_old_link_not_lost_on_rerun_search_failure(self):
        run=storage.create_run({'cities':['Germany · Berlin'],'categories':['Accounting Firms']})
        original=dict(ROW,**{'LinkedIn Company Page':'https://www.linkedin.com/company/silver-bridge/',
                              'LinkedIn Match Status':'Official website + indexed search match'})
        storage.save_lead(run,original,write_exports=False)
        storage.save_lead(run,dict(ROW,**{'LinkedIn Match Status':'Search unavailable'}),write_exports=False)
        row=storage.all_leads()[0]
        self.assertEqual(row['LinkedIn Company Page'],original['LinkedIn Company Page'])
        self.assertEqual(row['LinkedIn Match Status'],original['LinkedIn Match Status'])

if __name__=='__main__':unittest.main()
