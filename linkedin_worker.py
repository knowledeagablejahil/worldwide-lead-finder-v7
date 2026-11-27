"""Resume-safe, separate background search for company LinkedIn pages in saved leads."""
from __future__ import annotations
import json
import os
import threading
import traceback

import storage
from linkedin_discovery import search_company


def run():
    if not storage.acquire_linkedin_worker():
        return
    end=threading.Event()
    def heartbeat():
        while not end.wait(8):
            storage.set_setting('linkedin_heartbeat', storage.utcnow())
    thread=threading.Thread(target=heartbeat,daemon=True)
    thread.start()
    try:
        for job in storage.pending_linkedin():
            if storage.stop_linkedin_requested():
                break
            key=job['lead_key']
            try:
                row=json.loads(job['payload'])
                key_secret=storage.setting('brave_search_api_key') or os.getenv('BRAVE_SEARCH_API_KEY','')
                enrichment=search_company(row,api_key=key_secret)
                # Do not discard a previously confirmed company URL if a later
                # search engine returns weaker results or is rate-limited.
                old_url=row.get('LinkedIn Company Page','')
                old_status=row.get('LinkedIn Match Status','')
                if old_url and old_status.startswith(('Official website','Official-site')) and \
                   enrichment.get('LinkedIn Match Status') != 'Official website + indexed search match':
                    enrichment['LinkedIn Company Page']=old_url
                    enrichment['LinkedIn Match Status']=old_status
                    enrichment['LinkedIn Evidence']=row.get('LinkedIn Evidence','')
                row.update(enrichment)
                storage.update_existing_lead(key,row)
                storage.finish_linkedin(key)
            except Exception as exc:
                storage.finish_linkedin(key,error=str(exc))
                traceback.print_exc()
        try:
            from google_sheets_sync import sync_pending
            if not storage.cloud_sync_paused():
                sync_pending(max_batches=12)
        except Exception:
            pass
    finally:
        end.set()
        thread.join(timeout=1)
        storage.set_setting('linkedin_heartbeat','')

if __name__=='__main__':
    run()
