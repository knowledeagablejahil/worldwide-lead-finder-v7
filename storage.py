"""Durable SQLite checkpoints and immediately updated Excel-compatible files.

Saved leads live under the user's Windows Local AppData, not the program folder.
SQLite writes are committed before any attempt to regenerate Excel exports.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from engine import EXPORT_COLUMNS, csv_bytes
from quality import classify

BASE_DIR = Path(os.environ.get('PARTNER_FINDER_DATA_DIR', '') or
    (Path(os.environ['LOCALAPPDATA']) / 'ElevateBiz360' / 'EuropeanPartnerFinder'
     if os.environ.get('LOCALAPPDATA') else Path.home() / '.elevatebiz360' / 'EuropeanPartnerFinder'))
DB_FILE = BASE_DIR / 'partner_leads.sqlite3'
CSV_FILE = BASE_DIR / 'partner_leads_live.csv'
XLSX_FILE = BASE_DIR / 'partner_leads_live.xlsx'


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def _connection():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_FILE), timeout=30)
    try:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA busy_timeout=30000')
        with con:
            yield con
    finally:
        con.close()


def init():
    with _connection() as con:
        con.executescript('''
          CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            config TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            phase TEXT NOT NULL DEFAULT 'Waiting to start',
            started_at TEXT NOT NULL,
            heartbeat_at TEXT,
            completed_at TEXT,
            last_error TEXT DEFAULT ''
          );
          CREATE TABLE IF NOT EXISTS city_jobs (
            run_id INTEGER NOT NULL,
            country TEXT NOT NULL,
            city TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT DEFAULT '',
            total INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(run_id,country,city)
          );
          CREATE TABLE IF NOT EXISTS raw_leads (
            run_id INTEGER NOT NULL,
            lead_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            PRIMARY KEY(run_id,lead_key)
          );
          CREATE TABLE IF NOT EXISTS leads (
            lead_key TEXT PRIMARY KEY,
            run_id INTEGER NOT NULL,
            payload TEXT NOT NULL,
            saved_at TEXT NOT NULL
          );
          CREATE INDEX IF NOT EXISTS idx_raw_state ON raw_leads(run_id,state);
          CREATE TABLE IF NOT EXISTS cloud_settings (
            name TEXT PRIMARY KEY, value TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS cloud_synced (
            sheet_id TEXT NOT NULL, lead_key TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(sheet_id, lead_key)
          );
        ''')
        # V5: stop requests survive Streamlit refreshes and Windows restarts.
        run_cols = [row[1] for row in con.execute('PRAGMA table_info(runs)')]
        if 'stop_requested' not in run_cols:
            con.execute('ALTER TABLE runs ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0')
        # Migrate V3 sync state. Missing hashes force a safe one-time update.
        cols = [row[1] for row in con.execute('PRAGMA table_info(cloud_synced)')]
        if 'payload_hash' not in cols:
            con.execute("ALTER TABLE cloud_synced ADD COLUMN payload_hash TEXT NOT NULL DEFAULT ''")
        con.execute('''CREATE TABLE IF NOT EXISTS linkedin_jobs (
            lead_key TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'queued',
            attempted_at TEXT, error TEXT DEFAULT ''
        )''')
        con.execute('''CREATE TABLE IF NOT EXISTS research_jobs (
            lead_key TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'queued',
            attempted_at TEXT, error TEXT DEFAULT ''
        )''')


def key_for(row):
    # Same business in the same city should not be duplicated across scans.
    pieces = (str(row.get(k, '')) for k in ('Country', 'City', 'Business Name'))
    return hashlib.sha256('|'.join(re.sub(r'\W+', '', p.casefold()) for p in pieces).encode()).hexdigest()


def create_run(config):
    init()
    with _connection() as con:
        cursor = con.execute('INSERT INTO runs(config,status,started_at) VALUES (?, ?, ?)',
                             (json.dumps(config, ensure_ascii=False), 'queued', utcnow()))
        run_id = cursor.lastrowid
        for entry in config['cities']:
            country, city = entry.split(' · ', 1)
            con.execute('INSERT INTO city_jobs(run_id,country,city) VALUES (?,?,?)', (run_id, country, city))
    return run_id


def get_run(run_id):
    init()
    with _connection() as con:
        r = con.execute('SELECT * FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return dict(r) if r else None


def recent_runs(limit=12):
    init()
    with _connection() as con:
        return [dict(x) for x in con.execute('SELECT * FROM runs ORDER BY run_id DESC LIMIT ?', (limit,))]


def update_run(run_id, *, status=None, phase=None, last_error=None, completed=False):
    fields = ['heartbeat_at=?']
    vals = [utcnow()]
    if status is not None:
        fields.append('status=?')
        vals.append(status)
    if phase is not None:
        fields.append('phase=?')
        vals.append(phase)
    if last_error is not None:
        fields.append('last_error=?')
        vals.append(str(last_error)[:1500])
    if completed:
        fields.append('completed_at=?')
        vals.append(utcnow())
    vals.append(run_id)
    with _connection() as con:
        con.execute(f'UPDATE runs SET {", ".join(fields)} WHERE run_id=?', vals)


def save_discovery(run_id, country, city, rows):
    with _connection() as con:
        for row in rows:
            k = key_for(row)
            con.execute('''INSERT INTO raw_leads(run_id,lead_key,payload,state)
                           VALUES (?,?,?,'pending') ON CONFLICT(run_id,lead_key) DO NOTHING''',
                        (run_id, k, json.dumps(row, ensure_ascii=False)))
        con.execute("UPDATE city_jobs SET status='complete',error='',total=? WHERE run_id=? AND country=? AND city=?",
                    (len(rows), run_id, country, city))


def fail_city(run_id, country, city, error):
    with _connection() as con:
        con.execute("UPDATE city_jobs SET status='failed', error=? WHERE run_id=? AND country=? AND city=?",
                    (str(error)[:700], run_id, country, city))


def cities_todo(run_id):
    with _connection() as con:
        return [dict(x) for x in con.execute("SELECT * FROM city_jobs WHERE run_id=? AND status!='complete' ORDER BY country,city", (run_id,))]


def pending_rows(run_id):
    with _connection() as con:
        return [json.loads(r[0]) for r in con.execute("SELECT payload FROM raw_leads WHERE run_id=? AND state='pending' ORDER BY lead_key", (run_id,))]


def mark_excluded(run_id, row):
    with _connection() as con:
        con.execute("UPDATE raw_leads SET state='excluded' WHERE run_id=? AND lead_key=?", (run_id, key_for(row)))


def save_lead(run_id, row, *, write_exports=True):
    """The DB is the source of truth: success even when Excel is locked in Excel."""
    k = key_for(row)
    with _connection() as con:
        previous = con.execute('SELECT payload FROM leads WHERE lead_key=?', (k,)).fetchone()
    if previous:
        old_row = json.loads(previous['payload'])
        from linkedin_discovery import LINKEDIN_COLUMNS
        old_link=old_row.get('LinkedIn Company Page','')
        new_link=row.get('LinkedIn Company Page','')
        old_status=old_row.get('LinkedIn Match Status','')
        new_status=row.get('LinkedIn Match Status','')
        if old_link and (not new_link or (old_status.startswith(('Official website','Official-site'))
                                           and not new_status.startswith('Official website'))):
            for field in LINKEDIN_COLUMNS:
                if old_row.get(field): row[field]=old_row[field]
        # Rerunning an area must not erase contacts collected previously.
        for field in ('Website','Business Email','Email Source','Email Check','Phone',
                      'Phone Format Check','Phone Website Match','Firm Size',
                      'UAE Mention (checked pages)','Website Pages Checked',
                      'LinkedIn Company Page','LinkedIn Match Status','LinkedIn Evidence',
                      'LinkedIn Search Provider','LinkedIn Checked At (UTC)'):
            if not row.get(field) and old_row.get(field):
                row[field] = old_row[field]
        try:
            row['Score'] = max(int(row.get('Score') or 0), int(old_row.get('Score') or 0))
        except (ValueError, TypeError):
            pass
    row = classify(row)
    payload = json.dumps(row, ensure_ascii=False)
    with _connection() as con:
        con.execute('''INSERT INTO leads(lead_key,run_id,payload,saved_at) VALUES (?,?,?,?)
            ON CONFLICT(lead_key) DO UPDATE SET run_id=excluded.run_id,
            payload=excluded.payload,saved_at=excluded.saved_at''', (k, run_id, payload, utcnow()))
        con.execute("UPDATE raw_leads SET state='done' WHERE run_id=? AND lead_key=?", (run_id, k))
    if write_exports:
        export_all()


def all_leads():
    init()
    with _connection() as con:
        return [classify(json.loads(r[0])) for r in con.execute('SELECT payload FROM leads ORDER BY saved_at, lead_key')]


def metrics(run_id):
    with _connection() as con:
        jobs = [dict(x) for x in con.execute('SELECT country,city,status,total,error FROM city_jobs WHERE run_id=? ORDER BY country,city', (run_id,))]
        states = {x[0]: x[1] for x in con.execute('SELECT state,COUNT(*) FROM raw_leads WHERE run_id=? GROUP BY state', (run_id,))}
    return {'jobs': jobs, 'states': states, 'finished': states.get('done',0),
            'pending': states.get('pending',0), 'excluded': states.get('excluded',0)}


def export_all():
    """Write CSV atomically after *each* lead; also rebuild a native XLSX workbook."""
    rows = all_leads()
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CSV_FILE.with_suffix('.csv.tmp')
    tmp.write_bytes(csv_bytes(rows))
    os.replace(tmp, CSV_FILE)
    try:
        from excel_export import write_xlsx
        write_xlsx(XLSX_FILE, EXPORT_COLUMNS, rows)
        return True
    except (PermissionError, OSError):
        # Excel locks open workbooks on Windows; DB and CSV are still saved.
        return False


def request_stop_run(run_id):
    """Gracefully pause a search, preserving all raw and completed leads."""
    with _connection() as con:
        row = con.execute('SELECT status FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if not row or row['status'] in ('complete','partial','paused'):
            return False
        new_status = 'paused' if row['status'] != 'running' else 'running'
        phase = 'Paused — safe to resume' if new_status == 'paused' else 'Stopping safely after current request…'
        con.execute('UPDATE runs SET stop_requested=1,status=?,phase=? WHERE run_id=?', (new_status,phase,run_id))
    return True


def stop_run_requested(run_id):
    with _connection() as con:
        row = con.execute('SELECT stop_requested FROM runs WHERE run_id=?',(run_id,)).fetchone()
        return bool(row and row[0])


def clear_stop_run(run_id):
    with _connection() as con:
        con.execute('UPDATE runs SET stop_requested=0 WHERE run_id=?', (run_id,))


def cloud_sync_paused():
    return setting('sync_paused', '0') == '1'


def set_cloud_sync_paused(paused):
    set_setting('sync_paused', '1' if paused else '0')
    cloud_log_status('paused' if paused else 'ready',
                     'Sync paused. Saved leads remain queued.' if paused else 'Sync resumed. Pending leads can be uploaded.')


def acquire_sync_lease(stale_seconds=150):
    """Avoid duplicate simultaneous sync workers and Google request collisions."""
    import uuid
    token = uuid.uuid4().hex
    with _connection() as con:
        con.execute('BEGIN IMMEDIATE')
        r = con.execute("SELECT value FROM cloud_settings WHERE name='sync_lease'").fetchone()
        if r and r[0]:
            try:
                existing = json.loads(r[0])
                age = (datetime.now(timezone.utc)-datetime.fromisoformat(existing['at'])).total_seconds()
                if age < stale_seconds:
                    return None
            except (ValueError, KeyError, TypeError):
                pass
        lease=json.dumps({'token':token,'at':utcnow()})
        con.execute("INSERT INTO cloud_settings(name,value) VALUES('sync_lease',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(lease,))
    return token


def touch_sync_lease(token):
    with _connection() as con:
        r=con.execute("SELECT value FROM cloud_settings WHERE name='sync_lease'").fetchone()
        if r and r[0]:
            try:
                if json.loads(r[0]).get('token') == token:
                    con.execute("UPDATE cloud_settings SET value=? WHERE name='sync_lease'",(json.dumps({'token':token,'at':utcnow()}),))
                    return True
            except ValueError:
                pass
        return False


def release_sync_lease(token):
    with _connection() as con:
        r=con.execute("SELECT value FROM cloud_settings WHERE name='sync_lease'").fetchone()
        if r and r[0]:
            try:
                if json.loads(r[0]).get('token') == token:
                    con.execute("DELETE FROM cloud_settings WHERE name='sync_lease'")
            except ValueError:
                pass


def request_stop_research():
    set_setting('research_stop', '1')


def research_stop_requested():
    return setting('research_stop', '0') == '1'


def acquire_worker(run_id, stale_seconds=45):
    """One worker per scan, even when browser refreshes or launches twice."""
    from datetime import datetime, timezone
    with _connection() as con:
        con.execute('BEGIN IMMEDIATE')
        run = con.execute('SELECT status,heartbeat_at,stop_requested FROM runs WHERE run_id=?', (run_id,)).fetchone()
        if not run or run['status'] == 'complete' or (run['status']=='paused' and run['stop_requested']):
            return False
        if run['status'] == 'running' and run['heartbeat_at']:
            try:
                seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(run['heartbeat_at'])).total_seconds()
            except ValueError:
                seconds = stale_seconds + 1
            if seconds < stale_seconds:
                return False
        con.execute("UPDATE runs SET status='running',stop_requested=0,phase='Starting saved work',heartbeat_at=?,last_error='' WHERE run_id=?", (utcnow(),run_id))
        return True


def is_active(run):
    if not run or run.get('status') != 'running' or not run.get('heartbeat_at'):
        return False
    from datetime import datetime, timezone
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(run['heartbeat_at'])).total_seconds() < 45
    except ValueError:
        return False

# Google Sheets sync state. Namespaced by target sheet so switching sheets
# uploads the full saved history once to the new destination.
def setting(name, default=''):
    with _connection() as con:
        r = con.execute('SELECT value FROM cloud_settings WHERE name=?', (name,)).fetchone()
        return r['value'] if r else default


def set_setting(name, value):
    with _connection() as con:
        con.execute('INSERT INTO cloud_settings(name,value) VALUES(?,?) '
                    'ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, str(value)))


def cloud_settings():
    init()
    secret = setting('secret')
    if not secret:
        # One-time generation; keep it even as the app folder is upgraded.
        secret = secrets.token_urlsafe(36)
        with _connection() as con:
            con.execute('INSERT OR IGNORE INTO cloud_settings(name,value) VALUES (?,?)', ('secret', secret))
        secret = setting('secret')
    return {'sheet_id': setting('sheet_id'), 'script_url': setting('script_url'),
            'secret': secret, 'sync_status': setting('sync_status'),
            'sync_message': setting('sync_message'),
            'last_sync_at': setting('last_sync_at')}


def cloud_choose_sheet(sheet_id):
    old = setting('sheet_id')
    if old != sheet_id:
        with _connection() as con:
            con.execute('INSERT INTO cloud_settings(name,value) VALUES(?,?) '
                        'ON CONFLICT(name) DO UPDATE SET value=excluded.value', ('sheet_id', sheet_id))
            con.execute('INSERT INTO cloud_settings(name,value) VALUES(?,?) '
                        'ON CONFLICT(name) DO UPDATE SET value=excluded.value', ('script_url', ''))


def cloud_connect(url):
    set_setting('script_url', url)
    cloud_log_status('connected','Connected successfully; ready to sync')


def cloud_log_status(status, message):
    with _connection() as con:
        for name, value in (('sync_status', status), ('sync_message', str(message)[:500]),
                            ('last_sync_at', utcnow())):
            con.execute('INSERT INTO cloud_settings(name,value) VALUES(?,?) '
                        'ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name, value))


def row_signature(row):
    """Hash program-managed columns, so edits can be synced without duplicates."""
    cleaned = classify(row)
    values = [cleaned.get(k, '') for k in EXPORT_COLUMNS]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(',', ':'),
                                     default=str).encode('utf-8')).hexdigest()


def _cloud_records():
    sheet_id = setting('sheet_id')
    with _connection() as con:
        rows = con.execute('''SELECT l.lead_key,l.payload,l.saved_at,c.payload_hash
            FROM leads l LEFT JOIN cloud_synced c
            ON c.sheet_id=? AND c.lead_key=l.lead_key
            ORDER BY l.saved_at,l.lead_key''', (sheet_id,)).fetchall()
    return [(r['lead_key'], classify(json.loads(r['payload'])), r['payload_hash']) for r in rows]


def cloud_pending_count():
    return sum(1 for _, row, prior_hash in _cloud_records() if row_signature(row) != prior_hash)


def cloud_synced_count():
    sheet_id = setting('sheet_id')
    with _connection() as con:
        return con.execute('SELECT COUNT(*) FROM cloud_synced WHERE sheet_id=?', (sheet_id,)).fetchone()[0]


def cloud_pending_rows(limit=25):
    output = []
    for key, row, prior_hash in _cloud_records():
        fingerprint = row_signature(row)
        if fingerprint != prior_hash:
            output.append({'id': key, 'data': row, 'hash': fingerprint})
            if len(output) >= limit:
                break
    return output


def cloud_mark_synced(items):
    """Items: list of (id, fingerprint)."""
    if not items:
        return
    sheet_id = setting('sheet_id')
    normalized = []
    for item in items:
        if isinstance(item, str):
            item = (item, '')  # Backward compatibility with V3 callers.
        normalized.append((sheet_id, item[0], utcnow(), item[1]))
    with _connection() as con:
        con.executemany('''INSERT INTO cloud_synced(sheet_id,lead_key,synced_at,payload_hash)
            VALUES(?,?,?,?) ON CONFLICT(sheet_id,lead_key) DO UPDATE SET
            synced_at=excluded.synced_at,payload_hash=excluded.payload_hash''', normalized)


def research_candidates(include_retried=False):
    """Existing leads whose official website might contain missing contacts."""
    from engine import normalize_url
    from formation_filter import CATEGORY as formation_category, LEGACY_CATEGORY
    with _connection() as con:
        states = {r['lead_key']:r['state'] for r in con.execute('SELECT lead_key,state FROM research_jobs')}
        rows = con.execute('SELECT lead_key,payload FROM leads ORDER BY saved_at').fetchall()
    matches = []
    for r in rows:
        row = classify(json.loads(r['payload']))
        url = normalize_url(row.get('Website',''))
        if not url or any(x in url.lower() for x in ('facebook.com','instagram.com','linkedin.com')):
            continue
        verify_service = row.get('Category') == LEGACY_CATEGORY or (
            row.get('Category') == formation_category and
            row.get('Service Qualification') != 'Website evidence')
        if row.get('Business Email') and row.get('Phone') and not verify_service:
            continue
        if r['lead_key'] in states and not include_retried:
            continue
        matches.append(r['lead_key'])
    return matches


def queue_research(limit=50, include_retried=False):
    candidates = research_candidates(include_retried=include_retried)[:limit]
    with _connection() as con:
        for key in candidates:
            con.execute('''INSERT INTO research_jobs(lead_key,state) VALUES(?,'queued')
                ON CONFLICT(lead_key) DO UPDATE SET state='queued',error='' ''',(key,))
    return len(candidates)


def pending_research():
    with _connection() as con:
        return [dict(r) for r in con.execute('''SELECT r.lead_key,l.payload FROM research_jobs r
            JOIN leads l ON l.lead_key=r.lead_key WHERE r.state='queued' ORDER BY l.saved_at''')]


def research_status():
    with _connection() as con:
        return dict(con.execute('SELECT state,COUNT(*) FROM research_jobs GROUP BY state').fetchall())


def finish_research(key, *, error=''):
    with _connection() as con:
        con.execute('''UPDATE research_jobs SET state=?,attempted_at=?,error=? WHERE lead_key=?''',
                    ('failed' if error else 'done', utcnow(), str(error)[:300], key))


def update_existing_lead(key, updated, write_exports=True):
    """Keep stable lead key and any previously found LinkedIn page."""
    with _connection() as con:
        old = con.execute('SELECT payload FROM leads WHERE lead_key=?',(key,)).fetchone()
        if old:
            previous=json.loads(old[0])
            for field in ('LinkedIn Company Page','LinkedIn Match Status','LinkedIn Evidence',
                          'LinkedIn Search Provider','LinkedIn Checked At (UTC)'):
                if not updated.get(field) and previous.get(field):
                    updated[field]=previous[field]
        con.execute('UPDATE leads SET payload=?,saved_at=? WHERE lead_key=?',
                    (json.dumps(classify(updated), ensure_ascii=False), utcnow(), key))
    if write_exports:
        export_all()

def acquire_research_worker(stale_seconds=60):
    from datetime import datetime, timezone
    with _connection() as con:
        con.execute('BEGIN IMMEDIATE')
        r = con.execute("SELECT value FROM cloud_settings WHERE name='research_heartbeat'").fetchone()
        if r and r[0]:
            try:
                if (datetime.now(timezone.utc)-datetime.fromisoformat(r[0])).total_seconds() < stale_seconds:
                    return False
            except ValueError:
                pass
        con.execute("INSERT INTO cloud_settings(name,value) VALUES('research_heartbeat',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (utcnow(),))
        con.execute("INSERT INTO cloud_settings(name,value) VALUES('research_stop','0') ON CONFLICT(name) DO UPDATE SET value='0'")
    return True


def touch_research_worker():
    set_setting('research_heartbeat', utcnow())


def finish_research_worker():
    set_setting('research_heartbeat','')


def research_worker_active():
    from datetime import datetime, timezone
    beat=setting('research_heartbeat')
    if not beat:
        return False
    try:
        return (datetime.now(timezone.utc)-datetime.fromisoformat(beat)).total_seconds()<60
    except ValueError:
        return False


# V7: LinkedIn company-page research is an independent, resume-safe queue.
# It includes leads without websites and does not alter contact/formation statuses.
def linkedin_candidates(include_retried=False):
    with _connection() as con:
        statuses={r['lead_key']:r['state'] for r in con.execute('SELECT lead_key,state FROM linkedin_jobs')}
        leads=con.execute('SELECT lead_key,payload FROM leads ORDER BY saved_at,lead_key').fetchall()
    output=[]
    for item in leads:
        row=json.loads(item['payload'])
        if row.get('LinkedIn Company Page') and not include_retried:
            continue
        if (row.get('LinkedIn Checked At (UTC)') or item['lead_key'] in statuses) and not include_retried:
            continue
        if not row.get('Business Name'):
            continue
        output.append(item['lead_key'])
    return output


def queue_linkedin(limit=25,include_retried=False):
    keys=linkedin_candidates(include_retried)[:limit]
    with _connection() as con:
        for key in keys:
            con.execute('''INSERT INTO linkedin_jobs(lead_key,state) VALUES(?,'queued')
                ON CONFLICT(lead_key) DO UPDATE SET state='queued',error='' ''',(key,))
    return len(keys)


def pending_linkedin():
    with _connection() as con:
        return [dict(r) for r in con.execute('''SELECT j.lead_key,l.payload FROM linkedin_jobs j
            JOIN leads l ON l.lead_key=j.lead_key WHERE j.state='queued' ORDER BY l.saved_at''')]


def linkedin_research_status():
    with _connection() as con:
        return dict(con.execute('SELECT state,COUNT(*) FROM linkedin_jobs GROUP BY state').fetchall())


def finish_linkedin(key,error=''):
    with _connection() as con:
        con.execute('UPDATE linkedin_jobs SET state=?,attempted_at=?,error=? WHERE lead_key=?',
                    ('failed' if error else 'done',utcnow(),str(error)[:300],key))


def acquire_linkedin_worker(stale_seconds=60):
    with _connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute("SELECT value FROM cloud_settings WHERE name='linkedin_heartbeat'").fetchone()
        if row and row[0]:
            try:
                if (datetime.now(timezone.utc)-datetime.fromisoformat(row[0])).total_seconds()<stale_seconds:
                    return False
            except ValueError:
                pass
        con.execute("INSERT INTO cloud_settings(name,value) VALUES('linkedin_heartbeat',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(utcnow(),))
        con.execute("INSERT INTO cloud_settings(name,value) VALUES('linkedin_stop','0') ON CONFLICT(name) DO UPDATE SET value='0'")
    return True


def linkedin_worker_active():
    beat=setting('linkedin_heartbeat')
    if not beat: return False
    try: return (datetime.now(timezone.utc)-datetime.fromisoformat(beat)).total_seconds()<60
    except ValueError: return False


def request_stop_linkedin():
    set_setting('linkedin_stop','1')


def stop_linkedin_requested():
    return setting('linkedin_stop','0')=='1'
