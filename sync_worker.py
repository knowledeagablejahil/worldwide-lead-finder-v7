"""Manual sync command, launched in its own process so the browser stays usable."""
from __future__ import annotations
import argparse
import google_sheets_sync as sync

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-batches', type=int, default=80)
    args = parser.parse_args()
    result = sync.sync_pending(max_batches=max(1,min(args.max_batches,80)))
    print(result)
