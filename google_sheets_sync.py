"""Private Google Apps Script gateway. Syncs unsent leads, never deletes sheet rows.

Only posts to script.google.com/macros/s/<deployment>/exec to avoid arbitrary endpoints.
The SQLite database remains authoritative; failures do not lose local work.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
import storage

TEMPLATE = Path(__file__).with_name('google_script_template.js')
SHEET_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{15,160}$')
WEBAPP_PATTERN = re.compile(r'^/macros/s/[a-zA-Z0-9_-]+/exec$')


def extract_sheet_id(value: str) -> str:
    value = (value or '').strip()
    if 'docs.google.com' in value:
        url = urlparse(value)
        if url.scheme != 'https' or url.hostname != 'docs.google.com':
            raise ValueError('Use a Google Sheets link from docs.google.com.')
        match = re.fullmatch(r'/spreadsheets/d/([a-zA-Z0-9_-]+)(?:/.*)?', url.path)
        if not match:
            raise ValueError('This does not look like a Google Sheets URL.')
        value = match.group(1)
    if not SHEET_ID_PATTERN.fullmatch(value):
        raise ValueError('Paste your full Google Sheets URL.')
    return value


def validate_script_url(value: str) -> str:
    url = (value or '').strip()
    parts = urlparse(url)
    if parts.scheme != 'https' or parts.hostname != 'script.google.com' or not WEBAPP_PATTERN.fullmatch(parts.path) or parts.query or parts.fragment:
        raise ValueError('Paste the Apps Script Web app URL ending in /exec.')
    return url


def script_code(sheet_id: str, secret: str) -> str:
    if not SHEET_ID_PATTERN.fullmatch(sheet_id):
        raise ValueError('Missing Google Sheet ID')
    if len(secret) < 28:
        raise ValueError('Connection secret too short')
    return (TEMPLATE.read_text(encoding='utf-8')
            .replace('__SHEET_ID__', json.dumps(sheet_id))
            .replace('__SHARED_SECRET__', json.dumps(secret)))


def post(webapp_url: str, payload: dict) -> dict:
    url = validate_script_url(webapp_url)
    try:
        resp = requests.post(url, json=payload, timeout=(8, 45), allow_redirects=True,
                             headers={'User-Agent': 'ElevateBiz360-PartnerFinder/7'})
        resp.raise_for_status()
        result = resp.json()
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise ValueError(str(result.get('error', 'Unexpected response')) if isinstance(result, dict)
                             else 'Invalid Google response')
        return result
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f'Google connection failed: {str(e)[:200]}') from e
    except ValueError as e:
        raise RuntimeError(f'Google connection error: {str(e)[:200]}') from e


def test_endpoint(webapp_url: str, sheet_id: str, secret: str) -> dict:
    result = post(webapp_url, {'action': 'ping', 'secret': secret})
    if result.get('sheet_id') != sheet_id:
        raise RuntimeError('This script is connected to a different spreadsheet. Regenerate and redeploy the setup code.')
    if int(result.get('version') or 0) < 7:
        raise RuntimeError('V7 Google Apps Script needed for LinkedIn columns. Replace existing Apps Script code, then Deploy > Manage deployments > Edit > New version. Keep the same /exec URL and Google Sheet.')
    return result


def sync_pending(max_batches: int = 4) -> dict:
    """Cooperatively stoppable sync. Current Google request may finish before pause."""
    if storage.cloud_sync_paused():
        return {'sent':0, 'pending':storage.cloud_pending_count(), 'paused':True}
    config = storage.cloud_settings()
    if not config['sheet_id'] or not config['script_url']:
        return {'sent': 0, 'pending': storage.cloud_pending_count(), 'configured': False}
    lease = storage.acquire_sync_lease()
    if not lease:
        return {'sent': 0, 'pending': storage.cloud_pending_count(), 'busy': True}
    sent, inserted = 0, 0
    try:
        for _ in range(max_batches):
            if storage.cloud_sync_paused():
                storage.cloud_log_status('paused', 'Sync stopped after the current batch; unsent leads remain queued.')
                return {'sent': sent, 'pending': storage.cloud_pending_count(), 'paused': True}
            if not storage.touch_sync_lease(lease):
                raise RuntimeError('Sync lease lost; stopping to prevent duplicate uploads')
            batch = storage.cloud_pending_rows(limit=25)
            if not batch:
                break
            payload = {'action':'upsert', 'secret':config['secret'], 'rows':batch}
            try:
                result = post(config['script_url'], payload)
                if int(result.get('version') or 0) < 7:
                    raise RuntimeError('V7 Google receiver is required. Update the existing Apps Script and redeploy its SAME Web app as a New version. Existing rows remain safe.')
                if result.get('sheet_id') != config['sheet_id']:
                    raise RuntimeError('Connected sheet changed; sync halted')
                accepted = set(result.get('accepted_ids', []))
                expected = {row['id'] for row in batch}
                if not expected.issubset(accepted):
                    raise RuntimeError('Google did not confirm all lead IDs; none marked as synced')
                # Even when Stop Sync was clicked while Google was processing this
                # batch, safely acknowledge its completed work to avoid duplicates.
                storage.cloud_mark_synced([(row['id'],row['hash']) for row in batch])
                sent += len(expected)
                inserted += int(result.get('inserted', 0))
                storage.cloud_log_status('success', f'{sent} leads acknowledged; {inserted} new rows, {int(result.get("updated",0))} updated in last batch')
            except Exception as exc:
                storage.cloud_log_status('error', str(exc)[:500])
                return {'sent': sent, 'pending': storage.cloud_pending_count(),
                        'configured': True, 'error': str(exc)[:300]}
        return {'sent':sent, 'inserted':inserted, 'pending':storage.cloud_pending_count(), 'configured':True}
    finally:
        storage.release_sync_lease(lease)
