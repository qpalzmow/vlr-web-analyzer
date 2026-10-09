"""Hourly GitHub runner: collect using the same parsers and publish public counts."""
import argparse
import copy
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Timer

from app.analysis import SCHEMA_VERSION, analysis_status, bootstrap_analysis, refresh_analysis
from app.catalog import bootstrap_snapshot, build_snapshot
from app.db import init_db, get_catalog_snapshot, save_catalog_snapshot, get_analysis_teams
from app.snapshot_feed import install, validate


def write_snapshot(path, collection=None):
    payload = {'schema_version': 1, 'published_at': datetime.now(timezone.utc).isoformat(),
               'catalog': get_catalog_snapshot(),
               'analysis': {'schema_version': SCHEMA_VERSION, 'teams': get_analysis_teams()}}
    if collection is not None:
        payload['collection'] = copy.deepcopy(collection)
    validate(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return payload


class SnapshotCheckpoint:
    """Keep a recoverable checkpoint at most once per minute during collection."""
    def __init__(self, path, collection=None):
        self.path = path
        self.collection = collection
        self.last_written = time.monotonic()

    def __call__(self, progress):
        if self.collection is not None:
            self.collection['results'] = progress.copy()
        if time.monotonic() - self.last_written >= 60:
            if self.collection is None:
                write_snapshot(self.path)
            else:
                write_snapshot(self.path, self.collection)
            self.last_written = time.monotonic()


def collection_due(previous, now=None):
    """Check the durable catalog clock without initializing a database or scraping."""
    if not previous or not previous.exists():
        return True
    try:
        payload = validate(json.loads(previous.read_text(encoding='utf-8')))
        collected_at = datetime.fromisoformat(payload['catalog']['updated_at'])
        return ((now or datetime.now(timezone.utc)) - collected_at).total_seconds() >= 3600
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return True


def positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Time budget must be a positive number')
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('Time budget must be a positive number')
    return seconds


def finish_collection(collection, matches, stop):
    results = collection.get('results', {})
    analytics = analysis_status(matches)
    remaining = max(0, results.get('total', 0) - results.get('updated', 0) - results.get('failed', 0))
    partial = (remaining or results.get('failed', 0) or analytics['pending_teams']
               or analytics['failed_teams'] or analytics['stale_teams'])
    collection.update(status='partial' if partial or collection.get('error') else 'completed',
                      completed_at=datetime.now(timezone.utc).isoformat(),
                      budget_exhausted=stop.is_set(), remaining_teams=remaining,
                      analytics=analytics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--check-due', action='store_true', help='Print whether the previous catalog is at least an hour old')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--catalog-only', action='store_true', help='Refresh match context while preserving prepared team analysis')
    mode.add_argument('--analysis-only', action='store_true', help='Resume prepared team analysis without rebuilding the catalog')
    parser.add_argument('--catalog-max-seconds', type=positive_seconds, default=600,
                        help='Catalog request time budget; prior selections remain available at expiry')
    parser.add_argument('--max-seconds', type=positive_seconds, default=2400,
                        help='Analysis time budget; finished work is published when it expires')
    args = parser.parse_args()
    if args.check_due:
        print('true' if collection_due(args.previous) else 'false')
        return
    if not args.output:
        parser.error('--output is required when collecting data')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    collection = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                  'completed_at': None, 'mode': 'analysis_only' if args.analysis_only else
                  'catalog_only' if args.catalog_only else 'full'}
    init_db()
    bootstrap_snapshot()
    bootstrap_analysis()
    if args.previous and args.previous.exists():
        install(json.loads(args.previous.read_text(encoding='utf-8')))
    from app.scraper.http import set_collection_deadline
    if args.analysis_only:
        payload = get_catalog_snapshot()
        if not payload or not payload.get('ready_count'):
            raise ValueError('Analysis-only collection requires a prepared catalog')
    else:
        set_collection_deadline(args.catalog_max_seconds)
        try:
            payload = build_snapshot(get_catalog_snapshot())
        finally:
            set_collection_deadline(None)
        save_catalog_snapshot(payload)
    # Preserve a publishable catalog even if the runner reaches its time budget
    # during analysis. Periodic checkpoints avoid rewriting every team payload
    # after each individual team; the final snapshot always includes all results.
    write_snapshot(args.output, collection)
    if args.catalog_only:
        collection.update(status='catalog_only', completed_at=datetime.now(timezone.utc).isoformat(),
                          analytics=analysis_status(payload['matches']))
        write_snapshot(args.output, collection)
        logging.info('Catalog-only refresh: %s', payload['updated_at'])
        return
    stop = Event()
    timer = Timer(args.max_seconds, stop.set)
    timer.daemon = True
    set_collection_deadline(args.max_seconds)
    timer.start()
    try:
        collection['results'] = refresh_analysis(payload['matches'], force=False, stop=stop,
                                                on_progress=SnapshotCheckpoint(args.output, collection))
    except Exception as exc:
        collection['error'] = type(exc).__name__
        raise
    finally:
        timer.cancel()
        timer.join()
        set_collection_deadline(None)
        finish_collection(collection, payload['matches'], stop)
        write_snapshot(args.output, collection)
    if collection['status'] == 'partial':
        logging.warning('Partial analysis checkpoint: %s', collection)
    logging.info('Catalog: %s; analysis: %s', payload['updated_at'], collection)


if __name__ == '__main__':
    main()
