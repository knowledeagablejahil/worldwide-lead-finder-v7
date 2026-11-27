"""Worldwide partnership finder — recoverable searches, controls, Google Sheets sync."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import streamlit as st

import storage
import google_sheets_sync
from engine import csv_bytes, EXPORT_COLUMNS
from quality import CODES
from markets import CATEGORIES, MARKETS, REGIONS

APP_DIR = Path(__file__).resolve().parent
storage.init()
def _export_needs_upgrade():
    if not storage.CSV_FILE.exists():
        return True
    with storage.CSV_FILE.open('rb') as fp:
        return b'Contact Category' not in fp.readline()

if _export_needs_upgrade() or storage.setting('linkedin_v7_migrated') != '1':
    storage.export_all()  # Reclassify legacy generic consultant rows as unverified.
    storage.set_setting('formation_v6_migrated', '1')
    storage.set_setting('linkedin_v7_migrated', '1')
st.set_page_config(page_title='Worldwide Partnership Lead Finder', page_icon='🌍', layout='wide')
st.markdown('''<style>
.block-container {padding-top: 2rem;}
[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.18);border-radius: 14px;padding: 12px;}
</style>''', unsafe_allow_html=True)
st.title('Worldwide Partnership Lead Finder')
st.caption(f'ElevateBiz360 · V7 · {len(MARKETS)} countries & markets · Contact categories · Live Google Sheets sync')
st.success('Auto-save is ON. Previous leads and checkpoints are preserved. New: independent LinkedIn company-page lookup and a backfill search for saved businesses.')


def launch(run_id):
    logfile = storage.BASE_DIR / f'worker_{run_id}.log'
    storage.BASE_DIR.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, str(APP_DIR / 'worker.py'), '--run-id', str(run_id)]
    kwargs = {'cwd': str(APP_DIR), 'stdin': subprocess.DEVNULL, 'stdout': None,
              'stderr': subprocess.STDOUT, 'close_fds': True}
    if os.name == 'nt':
        kwargs['creationflags'] = (getattr(subprocess, 'DETACHED_PROCESS', 0) |
                                   getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    else:
        kwargs['start_new_session'] = True
    with logfile.open('ab') as log:
        kwargs['stdout'] = log
        subprocess.Popen(args, **kwargs)


def launch_sync_worker():
    logfile = storage.BASE_DIR / 'google_sync.log'
    kwargs = {'cwd':str(APP_DIR), 'stdin':subprocess.DEVNULL,
              'stderr':subprocess.STDOUT, 'close_fds':True}
    if os.name == 'nt':
        kwargs['creationflags']=(getattr(subprocess,'DETACHED_PROCESS',0)|
                                 getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
    else:
        kwargs['start_new_session']=True
    with logfile.open('ab') as log:
        subprocess.Popen([sys.executable,str(APP_DIR/'sync_worker.py'),
                          '--max-batches','80'],stdout=log,**kwargs)



# One-time Google Sheets setup. The recipient code is generated with a private,
# durable token stored in the same V2 local database. Users paste only the
# spreadsheet URL and deployment URL; there is no Google password handling.
cloud = storage.cloud_settings()
with st.expander('📗 Connect live Google Sheets', expanded=not bool(cloud['script_url'])):
    st.write('**Step 1:** Keep your existing Google Sheet (or create one at [sheets.new](https://sheets.new)). Enter its URL here.')
    sheet_default = (f"https://docs.google.com/spreadsheets/d/{cloud['sheet_id']}/edit"
                     if cloud['sheet_id'] else '')
    sheet_input = st.text_input('Your Google Sheet URL', value=sheet_default,
                                placeholder='https://docs.google.com/spreadsheets/d/.../edit')
    if st.button('Use this Google Sheet', key='choose_sheet'):
        try:
            sid = google_sheets_sync.extract_sheet_id(sheet_input)
            storage.cloud_choose_sheet(sid)
            st.success('Spreadsheet selected. Continue with Step 2 below.')
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if cloud['sheet_id']:
        code = google_sheets_sync.script_code(cloud['sheet_id'],cloud['secret'])
        st.warning('V7 adds LinkedIn columns. Upgrade the EXISTING Google Apps Script before syncing. Your current Sheet, Lead IDs and deployment URL stay the same.')
        st.markdown('**Step 2:** In your existing Google Sheet → **Extensions → Apps Script** → replace the old receiver code with the V7 code below (it contains the current Sheet ID and secret).')
        st.code(code, language='javascript')
        st.download_button('Download Google Apps Script code', data=code,
                           file_name='ElevateBiz360_Google_Sheets_Code.gs',
                           mime='text/plain', key='download_script')
        st.markdown('**Step 3:** Save the code. Choose **Deploy → Manage deployments → Edit (pencil) → New version → Deploy**. Reuse your CURRENT `/exec` Web app URL. Do not create a new deployment or spreadsheet. Keep the script and private token confidential.')
        endpoint = st.text_input('Paste deployed Web app URL', value=cloud['script_url'],
                                 placeholder='https://script.google.com/macros/s/.../exec')
        if st.button('Test connection & enable live upload', type='primary', key='connect_google'):
            try:
                url = google_sheets_sync.validate_script_url(endpoint)
                result = google_sheets_sync.test_endpoint(url, cloud['sheet_id'], cloud['secret'])
                storage.cloud_connect(url)
                st.success(f'Connected to Google Sheet: {result.get("sheet_name", "ready")}. '
                           'You can sync old saved leads now.')
                st.rerun()
            except Exception as e:
                st.error(f'Connection not confirmed: {e}')

if cloud['script_url']:
    st.caption('V7 requires the upgraded receiver. Your existing Sheet and /exec URL stay unchanged; pending local leads will not be marked synced until Google acknowledges V7.')
    if st.button('Verify Google receiver is V7', key='verify_v7'):
        try:
            result=google_sheets_sync.test_endpoint(cloud['script_url'],cloud['sheet_id'],cloud['secret'])
            st.success(f'Confirmed V{result["version"]}: connected to {result.get("sheet_name","Google Sheet")}.')
        except Exception as exc:
            st.error(str(exc))
    cloud_total = storage.cloud_pending_count()
    synced_total = storage.cloud_synced_count()
    col_a, col_b, col_c = st.columns(3)
    col_a.metric('Previously uploaded to Google Sheets', synced_total)
    col_b.metric('New / changed leads pending upload', cloud_total)
    col_c.metric('Last Google sync', cloud['sync_status'] or 'Connected')
    st.caption(f'Google sync status: {cloud["sync_message"] or "Ready"} · {cloud["last_sync_at"] or "Not synced yet"}')
    syncing_paused = storage.cloud_sync_paused()
    sync_left, sync_right = st.columns(2)
    with sync_left:
        if syncing_paused:
            if st.button('▶ Resume Sync', key='resume_sync', type='primary', use_container_width=True):
                storage.set_cloud_sync_paused(False)
                try:
                    launch_sync_worker()
                    st.toast('Google sync resumed. Pending rows will upload.')
                except Exception as exc:
                    st.error(f'Unable to launch sync: {exc}')
                st.rerun()
        else:
            if st.button('⏸ Stop Sync', key='stop_sync', use_container_width=True):
                storage.set_cloud_sync_paused(True)
                st.toast('Google sync will stop after any request already in progress.')
                st.rerun()
    with sync_right:
        if st.button('Sync all saved leads now', key='send_to_google',
                     use_container_width=True, disabled=syncing_paused):
            try:
                launch_sync_worker()
                st.toast('Sync started. The counters update after Google confirms batches.')
            except Exception as e:
                st.error(f'Could not start Google sync: {e}')
    if syncing_paused:
        st.warning('Google sync PAUSED. New leads still save locally and remain queued for upload.')
    else:
        st.caption('Stop Sync pauses automatic and manual Google uploads. An in-flight batch may finish; no saved leads are discarded.')

runs = storage.recent_runs()
with st.sidebar:
    st.header('1 · Worldwide markets and cities')
    regions = st.multiselect('Regions', REGIONS, default=['Europe'])
    available_countries = [c for c in MARKETS if MARKETS[c]['region'] in regions]
    country_defaults = [c for c in ['United Kingdom','Germany'] if c in available_countries]
    countries = st.multiselect('Countries & markets (excluding UAE)',
                               available_countries, default=country_defaults or available_countries[:1])
    opts = [f'{country} · {city}' for country in countries for city in MARKETS[country]['cities']]
    selected_cities = st.multiselect('Cities', opts, default=opts[:2])
    st.caption(f'{len(MARKETS)} markets · {len(REGIONS)} regions · up to 8 cities per search. '
               'Start with smaller batches to respect public OSM limits.')
    with st.expander('Suggested partnership markets'):
        st.markdown('**Europe:** UK, Germany, France, Netherlands, Switzerland, Ireland, Italy, Spain  \n'
                    '**North America:** US, Canada  \n'
                    '**Asia:** Singapore, Hong Kong, India, Malaysia  \n'
                    '**Middle East:** Saudi Arabia, Oman, Qatar, Bahrain  \n'
                    '**Africa:** South Africa, Mauritius, Kenya  \n'
                    '**Oceania:** Australia, New Zealand')
    st.header('2 · Business types')
    active_categories = [c for c in CATEGORIES if c != 'Business Consultants']
    categories = st.multiselect('Sectors', active_categories, default=active_categories)
    st.caption('Company Formation & Corporate Services replaces generic Business Consultancy. '
               'Only specific incorporation/setup evidence is accepted; general consultants are excluded.')
    radius = st.slider('Search radius per city (km)', 2, 18, 8)
    st.header('3 · Contact research')
    exclude_large = st.checkbox('Exclude known international chains', value=True)
    enrich_sites = st.checkbox('Check public business websites', value=True)
    site_limit = st.slider('Websites checked per run', 0, 100, 30, step=5, disabled=not enrich_sites)
    st.header('4 · LinkedIn company pages')
    st.caption('Search beyond business websites using indexed public web search results. Only LinkedIn company pages; no LinkedIn login or scraping.')
    linkedin_auto = st.checkbox('Search for LinkedIn company pages during new scans', value=True)
    linkedin_limit = st.slider('LinkedIn searches per new run', 0, 200, 40, step=10, disabled=not linkedin_auto)
    with st.expander('LinkedIn web search provider (optional)', expanded=False):
        configured=bool(storage.setting('brave_search_api_key','') or os.environ.get('BRAVE_SEARCH_API_KEY'))
        st.caption('Default: Bing RSS indexed search, no key required; may be rate-limited or return limited results. '
                   'Optional: Brave Search API for more consistent results (may require billing). '
                   'No LinkedIn login or profile scraping.')
        st.caption('Brave API key: ' + ('Configured' if configured else 'Not configured — Bing will be used'))
        new_key=st.text_input('Brave Search API key (optional)',value='',type='password',key='brave_key')
        if st.button('Save Brave Search API key',key='brave_save'):
            if new_key.strip():
                storage.set_setting('brave_search_api_key',new_key.strip())
                st.success('Saved locally on this computer; not sent to Google Sheets.')
            else:
                st.warning('Paste your key first.')
        if st.button('Remove saved Brave key / use Bing RSS',key='brave_remove'):
            storage.set_setting('brave_search_api_key','')
            st.success('Saved key cleared. Bing search will be used by default.')
    if 'Company Formation & Corporate Services' in categories and (not enrich_sites or site_limit == 0):
        st.warning('Formation searches without website checks may miss most relevant firms. '
                   'OpenStreetMap-only matches will require service verification.')
    new_run = st.button('Start NEW saved search', type='primary', use_container_width=True)
    active_runs = [r for r in runs if storage.is_active(r)]
    if active_runs:
        current = active_runs[0]
        st.header('Search controls')
        if storage.stop_run_requested(current['run_id']):
            st.warning(f'Stopping run #{current["run_id"]} after the current request')
        elif st.button('⏸ Stop active search', key='sidebar_stop_search', use_container_width=True):
            storage.request_stop_run(current['run_id'])
            st.toast(f'Stop requested for search #{current["run_id"]}; all saved leads remain safe.')
            st.rerun()
    if runs:
        st.header('Previous searches')
        selection = st.selectbox('View or resume', options=[r['run_id'] for r in runs],
            format_func=lambda rid: f'Run #{rid} · {next(r["status"] for r in runs if r["run_id"]==rid)}')
        if st.button('View selected search', use_container_width=True):
            st.session_state.selected_run = selection

if new_run:
    if not selected_cities or not categories:
        st.error('Select at least one city and one category.')
    elif len(selected_cities) > 8:
        st.error('Please select up to eight cities per batch to avoid overwhelming public OSM servers.')
    elif any(storage.is_active(r) for r in storage.recent_runs()):
        st.warning('A search is already running. You can view its progress below, or start another after it finishes.')
    else:
        config = {'cities': selected_cities, 'categories': categories, 'radius': radius,
                  'exclude_large': exclude_large, 'enrich_sites': enrich_sites, 'site_limit': site_limit,
                  'linkedin_search_limit': linkedin_limit if linkedin_auto else 0}
        rid = storage.create_run(config)
        st.session_state.selected_run = rid
        try:
            launch(rid)
            st.toast(f'Saved search #{rid} started; results will auto-save.')
        except Exception as exc:
            storage.update_run(rid, status='interrupted', phase='Could not start', last_error=str(exc))
            st.error(f'Unable to launch worker: {exc}')

st.caption(f'Live files are stored outside the application folder: `{storage.BASE_DIR}`')

@st.fragment(run_every='5s')
def live_dashboard():
    runs_now = storage.recent_runs()
    rid = st.session_state.get('selected_run') or (runs_now[0]['run_id'] if runs_now else None)
    if rid:
        run = storage.get_run(rid)
        if run:
            st.subheader(f'Saved search #{rid}')
            counts = storage.metrics(rid)
            a,b,c,d = st.columns(4)
            a.metric('Saved this run', counts['finished'])
            b.metric('Waiting for details', counts['pending'])
            c.metric('Cities completed', sum(j['status']=='complete' for j in counts['jobs']))
            d.metric('Cities total', len(counts['jobs']))
            st.write(f'**Status:** {run["status"].title()} · {run["phase"]}')
            if storage.is_active(run):
                if storage.stop_run_requested(rid):
                    st.warning('Stop requested. Waiting for the active map or website request to finish; saved leads are safe.')
                elif st.button('⏸ Stop Search', key=f'stop_run_{rid}', use_container_width=True):
                    storage.request_stop_run(rid)
                    st.toast('Stopping at the next safe checkpoint; progress is saved.')
                    st.rerun()
                st.caption('The scan continues when the browser is closed, but not after you press Stop Search. It needs the PC awake.')
            elif run['status'] != 'complete':
                if st.button('▶ Resume saved search', key=f'resume_{rid}', type='primary'):
                    try:
                        storage.clear_stop_run(rid)
                        launch(rid)
                        st.toast('Resuming from saved leads and unfinished cities.')
                    except Exception as exc:
                        st.error(f'Could not resume: {exc}')
            if run.get('last_error'):
                with st.expander('Warnings / errors'):
                    st.code(run['last_error'])
            if counts['jobs']:
                with st.expander('City checkpoints'):
                    st.dataframe(counts['jobs'], hide_index=True, use_container_width=True)

    rows = storage.all_leads()
    st.divider()
    st.subheader('All saved partnership prospects')
    li_count=sum(bool(r.get('LinkedIn Company Page')) for r in rows)
    li_confirmed=sum('Official website + indexed' in r.get('LinkedIn Match Status','') for r in rows)
    st.caption(f'LinkedIn company-page URLs found: **{li_count}** · search + official site corroborated: **{li_confirmed}**. Other matches require review.')
    availability = Counter(r.get('Contact Category','').split(' ')[0] for r in rows)
    queues = Counter(r.get('Workflow Queue','') for r in rows)
    a,b,c,d = st.columns(4)
    a.metric('Total saved leads', len(rows))
    b.metric('Ready for Outreach', queues.get('Ready for Outreach',0))
    c.metric('Needs Contact Research', queues.get('Needs Contact Research',0))
    d.metric('Hold / Review', queues.get('Hold',0) + queues.get('Needs Service Verification',0))
    if rows:
        st.caption('Contact categories count fields present; separate verification status does not prove phone activity or email delivery.')
        with st.expander('What A1–D and the verification labels mean'):
            st.markdown('**A1**: Website + email + phone · **A2**: Website + email · **A3**: Website + phone · '
                        '**B1**: Email + phone · **B2**: Email only · **B3**: Phone only · '
                        '**C1**: Website only · **D**: No contact.\n\n'
                        '**Partnership Fit** is separate: High is a promising clue, not proof of company size. '
                        '**Verification** distinguishes source/format checks from active contact confirmation.')
        cats=st.columns(8)
        for i,code in enumerate(['A1','A2','A3','B1','B2','B3','C1','D']):
            cats[i].metric(code,availability.get(code,0))
        countries_here = sorted({r['Country'] for r in rows})
        filt_countries = st.multiselect('Country filter', countries_here, default=countries_here, key='country_filter')
        filt_fit = st.multiselect('Partnership fit', ['High','Medium','Low','Unknown'], default=['High','Medium','Low','Unknown'], key='fit_filter')
        linkedin_filter = st.selectbox('LinkedIn filter', ['All','Has company page','Missing company page','Needs match review'], key='linkedin_filter')
        subset = [r for r in rows if r['Country'] in filt_countries and r['Partnership Fit'] in filt_fit]
        if linkedin_filter == 'Has company page':
            subset=[r for r in subset if r.get('LinkedIn Company Page')]
        elif linkedin_filter == 'Missing company page':
            subset=[r for r in subset if not r.get('LinkedIn Company Page')]
        elif linkedin_filter == 'Needs match review':
            subset=[r for r in subset if 'review' in r.get('LinkedIn Match Status','').lower()]
        view_all, view_ready, view_service, view_research, view_hold, view_linkedin = st.tabs(
            ['Master Leads','Ready for Outreach','Verify Formation Service','Needs Contact Research','Hold','LinkedIn Pages'])
        cols = ('Country','City','Business Name','Category','Service Qualification','Contact Category',
                'Contact Verification','Partnership Fit','Fit Evidence','Next Action',
                'Website','Business Email','Phone','LinkedIn Company Page',
                'LinkedIn Match Status','LinkedIn Evidence','LinkedIn Search Provider','OSM Listing')
        for tab,queue in ((view_all,None),(view_ready,'Ready for Outreach'),
                          (view_service,'Needs Service Verification'),
                          (view_research,'Needs Contact Research'),(view_hold,'Hold'),(view_linkedin,'LinkedIn')):
            with tab:
                visible=[r for r in subset if queue is None or
                         (r.get('LinkedIn Company Page') if queue=='LinkedIn' else r['Workflow Queue']==queue)]
                fit_rank={'High':0,'Medium':1,'Unknown':2,'Low':3}
                contact_rank={c:i for i,c in enumerate(['A1','A2','A3','B1','B2','B3','C1','D'])}
                visible.sort(key=lambda r:(fit_rank.get(r.get('Partnership Fit'),9),
                    contact_rank.get(r.get('Contact Category','').split(' ')[0],9),
                    r.get('Country',''),r.get('Business Name','')))
                st.caption(f'{len(visible)} matching prospects')
                st.dataframe([{k:r.get(k,'') for k in cols} for r in visible],
                             use_container_width=True, hide_index=True, height=340,
                             column_config={'LinkedIn Company Page':st.column_config.LinkColumn('LinkedIn Company Page')})
                st.download_button('Download this view (CSV)',data=csv_bytes(visible),
                                   file_name='partners_'+(queue or 'all').replace(' ','_').lower()+'.csv',
                                   mime='text/csv',key='dl_'+str(queue))
        with st.expander('🔎 Find LinkedIn company pages for saved businesses',expanded=True):
            li_status=storage.linkedin_research_status()
            st.write('Searches the public web index for LinkedIn **company** pages even if a business has no website. '
                     'Matching uses name, city and country; uncertain matches are flagged for review. '
                     'Saved leads are updated using their existing Lead IDs, including in Google Sheets after upgrading its V7 receiver.')
            st.caption(f'Unsearched leads: {len(storage.linkedin_candidates())} · '
                       f'queued: {li_status.get("queued",0)} · completed: {li_status.get("done",0)} · '
                       f'failed: {li_status.get("failed",0)}')
            linkedin_n=st.slider('How many saved businesses to search',5,100,25,5,key='linkedin_n')
            linkedin_retry=st.checkbox('Recheck already searched/matched LinkedIn pages',key='linkedin_retry',value=False)
            if storage.linkedin_worker_active():
                st.info('LinkedIn lookup is running in the background; results save after every business.')
                if st.button('⏸ Stop LinkedIn Search',key='stop_linkedin'):
                    storage.request_stop_linkedin()
                    st.toast('Stopping after current search request; unfinished leads stay queued.')
            if st.button('Find LinkedIn company pages',type='primary',key='launch_linkedin',
                         disabled=storage.linkedin_worker_active()):
                queued=storage.queue_linkedin(limit=linkedin_n,include_retried=linkedin_retry)
                if queued or li_status.get('queued',0):
                    logfile=storage.BASE_DIR/'linkedin_worker.log'
                    opts={'cwd':str(APP_DIR),'stdin':subprocess.DEVNULL,
                          'stderr':subprocess.STDOUT,'close_fds':True}
                    if os.name=='nt':
                        opts['creationflags']=(getattr(subprocess,'DETACHED_PROCESS',0)|
                                               getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
                    else:
                        opts['start_new_session']=True
                    with logfile.open('ab') as log:
                        subprocess.Popen([sys.executable,str(APP_DIR/'linkedin_worker.py')],stdout=log,**opts)
                    st.toast(f'{queued} businesses queued for web search. Results will save automatically.')
                else:
                    st.info('No unsearched companies remain. Enable Recheck to try them again.')
        with st.expander('Research missing contacts and verify formation companies'):
            st.write('Rechecks official websites for existing leads missing contacts or awaiting company-formation verification. '
                     'Small batches respect website robots rules. The Google Sheet updates the existing Lead ID after a new contact is found.')
            st.caption(f'Available to research: {len(storage.research_candidates())}; '
                       f'queued: {storage.research_status().get("queued",0)}; '
                       f'completed: {storage.research_status().get("done",0)}')
            research_n=st.slider('Businesses to check',5,50,20,5,key='research_n')
            allow_retry=st.checkbox('Retry websites already researched',value=False,key='research_retry')
            if storage.research_worker_active():
                if st.button('⏸ Stop Contact Research', key='stop_research'):
                    storage.request_stop_research()
                    st.toast('Research will stop after its current website check; queued items are preserved.')
            if st.button('Research contacts / verify incorporation services',type='primary',key='research_action'):
                if storage.research_worker_active():
                    st.warning('A website research job is already active.')
                else:
                    queued=storage.queue_research(limit=research_n,include_retried=allow_retry)
                    if queued or storage.research_status().get('queued',0):
                        logfile=storage.BASE_DIR/'research_worker.log'
                        opts={'cwd':str(APP_DIR),'stdin':subprocess.DEVNULL,
                              'stderr':subprocess.STDOUT,'close_fds':True}
                        if os.name=='nt':
                            opts['creationflags']=(getattr(subprocess,'DETACHED_PROCESS',0)|
                                                   getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
                        else:
                            opts['start_new_session']=True
                        with logfile.open('ab') as log:
                            subprocess.Popen([sys.executable,str(APP_DIR/'research_worker.py')],stdout=log,**opts)
                        st.toast(f'{queued} new businesses queued for website contact research. Reload later to see results.')
                    else:
                        st.info('No unresearched websites with missing contacts or unverified formation services.')
    left,right = st.columns(2)
    if storage.XLSX_FILE.exists():
        left.download_button('Download latest Excel (.xlsx)', data=storage.XLSX_FILE.read_bytes(), file_name='worldwide_partnership_leads.xlsx',
                             mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', type='primary', key='all_xlsx')
    if storage.CSV_FILE.exists():
        right.download_button('Download live CSV', data=storage.CSV_FILE.read_bytes(), file_name='worldwide_partnership_leads.csv', mime='text/csv', key='all_csv')
    if st.button('Refresh Excel/CSV files', key='force_export'):
        try:
            workbook_ok = storage.export_all()
            if workbook_ok:
                st.success('Excel and CSV now match all saved leads.')
            else:
                st.warning('Excel is locked. Close the workbook in Excel and try again. The leads are safe in SQLite and CSV.')
        except Exception as exc:
            st.error(f'Export failed: {exc}')

live_dashboard()
st.caption('V7 Google Sheets inserts or updates by Lead ID after the V7 Apps Script is redeployed;  it receives changed leads during scans and when you click Sync all saved leads now.  Excel saves to disk after every processed lead. An open workbook may be locked by Microsoft Excel and does not automatically refresh its visible rows; close and reopen it to see the newest data. CSV and the SQLite backup continue saving.')
with st.expander('Accuracy and compliant outreach'):
    st.write('LinkedIn company page links come from public search-engine indexes (Bing RSS, or Brave Search API with your own key), and may be missing or incorrect. These results are not verified LinkedIn ownership. The app never scrapes LinkedIn or personal profiles. OSM uses a broad consulting tag. Company formation matches are screened by specific OSM listing text or service language on checked public website pages. Website evidence is not a guarantee; OSM-only and legacy consultancy matches require manual verification. OpenStreetMap is incomplete. Email MX checks do not prove inbox delivery; phone formatting is not an active-line test. Firm size is not confirmed. Review GDPR, ePrivacy, national direct-marketing rules and regulated-profession referral restrictions before contacting prospects. © OpenStreetMap contributors (ODbL). Use small city batches; public Overpass servers may rate-limit large or frequent searches.')
