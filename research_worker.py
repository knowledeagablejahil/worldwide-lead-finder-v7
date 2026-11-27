"""Resume-safe research for existing leads with official websites and missing contacts."""
from __future__ import annotations
import json
import threading
import traceback
import storage
from engine import refine
from formation_filter import CATEGORY as formation_category, LEGACY_CATEGORY


def run():
    if not storage.acquire_research_worker():
        return
    stop=threading.Event()
    def beat():
        while not stop.wait(8):
            storage.touch_research_worker()
    thread=threading.Thread(target=beat,daemon=True)
    thread.start()
    try:
        for job in storage.pending_research():
            if storage.research_stop_requested():
                break
            key=job['lead_key']
            try:
                old=json.loads(job['payload'])
                # Respect robots, website connection limits and conservatively
                # preserve existing fields when a website has no new details.
                candidate = dict(old)
                # Legacy generic consultancy rows must demonstrate company
                # formation services before promotion into the new category.
                if candidate.get('Category') == LEGACY_CATEGORY:
                    candidate['Category'] = formation_category
                result=refine([candidate],max_websites=1,exclude_large=False,
                              should_stop=storage.research_stop_requested)
                if not result:
                    if storage.research_stop_requested():
                        break
                    # No evidence: retain old record and ID; it stays held.
                    storage.finish_research(key)
                    continue
                new=result[0]
                for field in ('Business Email','Phone','Website'):
                    if not new.get(field) and old.get(field):
                        new[field]=old[field]
                storage.update_existing_lead(key,new)
                storage.finish_research(key)
            except Exception as exc:
                storage.finish_research(key,error=str(exc))
                traceback.print_exc()
        try:
            from google_sheets_sync import sync_pending
            if not storage.cloud_sync_paused():
                sync_pending(max_batches=12)
        except Exception:
            pass  # Local copy remains safe. Status is recorded by sync_pending.
    finally:
        stop.set()
        thread.join(timeout=1)
        storage.finish_research_worker()

if __name__=='__main__':
    run()
