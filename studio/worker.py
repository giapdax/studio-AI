"""Independent durable queue consumer; paid jobs require an explicit CLI flag."""
import argparse
import json
import os
import threading
from pathlib import Path

from . import secrets
from .jobs import Runner
from .storage import Store


def eligible_jobs(store, allow_paid=False, identities=None):
    rows = store.rows("SELECT * FROM jobs WHERE status='queued' AND mode IN ('mock','real') ORDER BY created,id")
    return [row for row in rows if (not identities or row['id'] in identities) and (row['mode'] == 'mock' or (allow_paid and json.loads(row['snapshot'])['options'].get('authorized') is True))]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fashion AI Studio worker. Default: MOCK only; no paid API calls.')
    parser.add_argument('--data-dir', default=os.getenv('STUDIO_DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data')))
    parser.add_argument('--concurrency', type=int, choices=(1, 2, 3), default=1)
    parser.add_argument('--once', action='store_true', help='Process currently eligible queue, then exit.')
    parser.add_argument('--allow-paid', action='store_true', help='Authorize paid API jobs previously authorized in the UI.')
    parser.add_argument('--job', action='append', help='Only these job IDs; may resume failed/interrupted/paused jobs.')
    parser.add_argument('--resume-mock', action='store_true', help='Requeue interrupted MOCK jobs automatically.')
    args = parser.parse_args(argv)
    store = Store(args.data_dir)
    store.seed_scripts(Path(__file__).resolve().parents[1] / 'scripts.json')
    store.recover()
    for identity in args.job or []:
        job = store.job(identity)
        if job['mode'] == 'real' and not args.allow_paid:
            parser.error('Use --allow-paid to authorize processing a real API job.')
        store.execute("UPDATE jobs SET status='queued',pause_requested=0 WHERE id=? AND status IN ('failed','interrupted','paused')", (identity,))
    runner = Runner(store, args.concurrency)
    selected = set()
    interrupted = False
    try:
        while True:
            store.recover()
            if args.resume_mock:
                store.execute("UPDATE jobs SET status='queued',pause_requested=0 WHERE mode='mock' AND status='interrupted'")
            jobs = eligible_jobs(store, args.allow_paid, set(args.job or []))
            for job in jobs:
                # Read keys only for paid work, never serialize them or include in logs.
                keys = (secrets.read('openai'), secrets.read('google')) if job['mode'] == 'real' else ('', '')
                if runner.submit(job['id'], keys):
                    selected.add(job['id'])
                    print(json.dumps({'job_id': job['id'], 'mode': job['mode'], 'event': 'queued'}, ensure_ascii=True), flush=True)
            if args.once:
                break
            threading.Event().wait(2)
    except KeyboardInterrupt:
        interrupted = True
        with runner.lock:
            identities = list(runner.pending)
        for identity in identities:
            store.pause(identity)
        print('Stopping after current provider request completes. Saved outputs are retained.', flush=True)
    finally:
        runner.pool.shutdown(wait=True, cancel_futures=interrupted)
    outcomes = [store.job(identity) for identity in sorted(selected)]
    for job in outcomes:
        print(json.dumps({'job_id': job['id'], 'status': job['status'], 'stage': job['stage']}, ensure_ascii=True), flush=True)
    return 1 if any(job['status'] == 'failed' for job in outcomes) else 0


if __name__ == '__main__':
    raise SystemExit(main())
