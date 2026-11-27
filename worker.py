"""Background worker. Browser tab and Streamlit session are NOT required to stay open.

The machine must stay awake. If it shuts down, unfinished rows persist in SQLite.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import traceback

import storage
import google_sheets_sync
from engine import query_city, refine


def heartbeat(run_id, stop_event):
    while not stop_event.wait(6):
        try:
            storage.update_run(run_id)
        except Exception:
            pass  # Worker loop will surface any real database error.


def cloud_loop(stop_event):
    # Sync periodically while search is running, without delaying local saves.
    # Errors are recorded and retried on a later cycle; never stop the lead scan.
    while not stop_event.wait(10):
        if storage.cloud_sync_paused():
            continue
        try:
            google_sheets_sync.sync_pending(max_batches=3)
        except Exception as exc:
            storage.cloud_log_status('error', str(exc)[:300])


def process(run_id):
    if not storage.acquire_worker(run_id):
        return
    stopping = threading.Event()
    beat = threading.Thread(target=heartbeat, args=(run_id, stopping), daemon=True)
    beat.start()
    cloud_stop = threading.Event()
    cloud_thread = threading.Thread(target=cloud_loop, args=(cloud_stop,), daemon=True)
    cloud_thread.start()
    try:
        config = json.loads(storage.get_run(run_id)['config'])
        failed = []
        todo = storage.cities_todo(run_id)
        for i, city_item in enumerate(todo):
            if storage.stop_run_requested(run_id):
                break
            country, city = city_item['country'], city_item['city']
            storage.update_run(run_id, phase=f'Discovering {city}, {country} ({i+1}/{len(todo)})')
            try:
                rows = query_city(country, city, config['radius'], config['categories'])
                storage.save_discovery(run_id, country, city, rows)
            except Exception as exc:
                storage.fail_city(run_id, country, city, exc)
                failed.append(f'{country} / {city}: {exc}')
            if i + 1 < len(todo):
                for _ in range(4):
                    if storage.stop_run_requested(run_id):
                        break
                    time.sleep(.5)

        if storage.stop_run_requested(run_id):
            storage.update_run(run_id, status='paused', phase='Paused — saved progress can be resumed')
            return

        rows = storage.pending_rows(run_id)
        storage.update_run(run_id, phase=f'Checking contact details for {len(rows)} saved candidates')
        # On resume, leads processed previously are excluded from rows, so no earlier
        # websites are rechecked merely because the browser or computer closed.
        on_row = lambda row: storage.save_lead(run_id, row)
        on_skip = lambda row: storage.mark_excluded(run_id, row)
        def update_progress(index, total, sites):
            if index % 5 == 0 or index == total:
                storage.update_run(run_id, phase=f'Enriching contact details: {index}/{total} remaining candidates')
        refine(rows, max_websites=config['site_limit'] if config['enrich_sites'] else 0,
               exclude_large=config['exclude_large'], on_row=on_row,
               on_skip=on_skip, callback=update_progress,
               should_stop=lambda: storage.stop_run_requested(run_id),
               linkedin_search_limit=int(config.get('linkedin_search_limit',0)),
               linkedin_api_key=storage.setting('brave_search_api_key',''))
        if storage.stop_run_requested(run_id):
            storage.update_run(run_id, status='paused', phase='Paused — saved progress can be resumed')
            return
        # Export once more for empty-result runs, including a workbook with headers.
        excel_ok = storage.export_all()
        final_jobs = storage.metrics(run_id)['jobs']
        failed_now = [f'{j["country"]} / {j["city"]}: {j["error"]}' for j in final_jobs if j['status']=='failed']
        if failed_now:
            storage.update_run(run_id, status='partial', phase='Partial — failed cities can be retried',
                               last_error='; '.join(failed_now)[:1500])
        else:
            storage.update_run(run_id, status='complete', phase='Completed — all leads saved', completed=True,
                               last_error='' if excel_ok else 'Excel workbook locked; CSV and database saved. Close Excel and press Refresh Excel files.')
    except Exception:
        storage.update_run(run_id, status='interrupted', phase='Interrupted — resume saved progress',
                           last_error=traceback.format_exc()[-1600:])
        traceback.print_exc()
    finally:
        cloud_stop.set()
        cloud_thread.join(timeout=2)
        if not storage.cloud_sync_paused():
            try:
                google_sheets_sync.sync_pending(max_batches=12)
            except Exception as exc:
                storage.cloud_log_status('error', str(exc)[:300])
        stopping.set()
        beat.join(timeout=1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', type=int, required=True)
    args = parser.parse_args()
    process(args.run_id)
