"""Collect public snapshots with validated file-first checkpoints."""
import argparse
import copy
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Timer

from app import db
from app.analysis import SCHEMA_VERSION, analysis_status, bootstrap_analysis, refresh_analysis
from app.catalog import CatalogCollectionError, bootstrap_snapshot, build_snapshot
from app.db import init_db, get_catalog_snapshot, save_catalog_snapshot, get_analysis_teams
from app.snapshot_feed import validate

logger = logging.getLogger(__name__)
RETRY_SECONDS = 900


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_payload(catalog=None, collection=None, teams=None):
    """Construct and validate a candidate without modifying its database."""
    catalog = copy.deepcopy(catalog if catalog is not None else get_catalog_snapshot())
    payload = {'schema_version': 1, 'published_at': now_iso(), 'catalog': catalog,
               'analysis': {'schema_version': SCHEMA_VERSION,
                            'teams': copy.deepcopy(teams if teams is not None else get_analysis_teams())}}
    if collection is not None:
        metadata = copy.deepcopy(collection)
        if catalog.get('collection'):
            metadata['catalog'] = copy.deepcopy(catalog['collection'])
        payload['collection'] = metadata
    validate(payload)
    return payload


def atomic_write(path, payload):
    validate(payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def write_snapshot(path, collection=None, *, catalog=None, checkpoint=None, update_db=False):
    """Validate, replace the persistent file, replace output, then update SQLite."""
    payload = make_payload(catalog, collection)
    if checkpoint is not None and Path(checkpoint) != Path(path):
        atomic_write(checkpoint, payload)
    atomic_write(path, payload)
    if update_db:
        save_catalog_snapshot(payload['catalog'])
    return payload


def checkpoint_path(value=None):
    return Path(value) if value is not None else Path(db.DB_DIR) / 'collector-checkpoint.json'


def load_valid(path):
    try:
        return validate(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning('Ignoring invalid snapshot file %s: %s', path, type(exc).__name__)
        return None


def seed_payload():
    root = Path(__file__).resolve().parents[1] / 'data'
    try:
        catalog = json.loads((root / 'catalog_seed.json').read_text(encoding='utf-8'))
        analysis = json.loads((root / 'analysis_seed.json').read_text(encoding='utf-8'))
        return validate({'schema_version': 1, 'published_at': catalog['updated_at'],
                         'catalog': catalog, 'analysis': analysis})
    except (OSError, ValueError, KeyError, TypeError):
        return None


def recover_snapshot(output, previous=None, checkpoint=None):
    """Files determine the catalog generation; cached DB clocks never select it."""
    checkpoint = checkpoint_path(checkpoint)
    candidates, seen = [], set()
    for path in (checkpoint, previous, output):
        if path is not None and str(Path(path).resolve()) not in seen:
            seen.add(str(Path(path).resolve()))
            candidate = load_valid(path) if Path(path).exists() else None
            if candidate is not None:
                candidates.append(candidate)
    if not candidates:
        seed = seed_payload()
        if seed is None:
            raise ValueError('No validated public snapshot or checkpoint is available')
        candidates.append(seed)
    chosen = copy.deepcopy(max(candidates, key=lambda p: (
        datetime.fromisoformat(p['catalog']['updated_at']),
        datetime.fromisoformat(p['published_at']))))
    teams = get_analysis_teams()
    for candidate in candidates:
        teams = db.merge_analysis_records(teams, candidate['analysis']['teams'])
    chosen['analysis']['teams'] = teams
    validate(chosen)
    atomic_write(checkpoint, chosen)
    if Path(output) != checkpoint:
        atomic_write(output, chosen)
    # This is deliberately separate from the normal server import's monotonic guard.
    db.restore_collector_snapshot(chosen['catalog'], chosen['analysis']['teams'])
    return chosen


def catalog_phase(catalog):
    if catalog.get('collection'):
        return copy.deepcopy(catalog['collection'])
    failures = copy.deepcopy(catalog.get('failures', []))
    return {'status': 'partial' if failures else 'completed',
            'catalog_generation': catalog['generation'],
            'started_at': catalog['updated_at'], 'completed_at': catalog['updated_at'],
            'budget_exhausted': False, 'failures': failures,
            'next_retry_at': None}


def set_catalog_phase(catalog, phase):
    result = copy.deepcopy(catalog)
    result['collection'] = copy.deepcopy(phase)
    return result


def combined_status(collection, analysis_status_value=None):
    state = collection.get('catalog', {}).get('status', 'completed')
    if state in ('retained_previous', 'failed'):
        return state
    if state == 'partial' or analysis_status_value in ('partial', 'failed', 'running'):
        return 'partial'
    return 'completed'


def collection_due(previous, now=None):
    if not previous or not previous.exists():
        return True
    payload = load_valid(previous)
    if payload is None:
        return True
    current = now or datetime.now(timezone.utc)
    collection = payload.get('collection', {})
    phases = [payload['catalog'].get('collection') or collection.get('catalog', {}),
              collection.get('analysis', {})]
    failed = [p for p in phases if p.get('status') in ('partial', 'retained_previous', 'failed', 'running')]
    if failed:
        retries = []
        for phase in failed:
            if phase.get('next_retry_at'):
                retries.append(datetime.fromisoformat(phase['next_retry_at']))
            else:
                clock = phase.get('completed_at') or phase.get('started_at') or payload['catalog']['updated_at']
                retries.append(datetime.fromisoformat(clock) + timedelta(seconds=RETRY_SECONDS))
        return current >= min(retries)
    # Legacy partial metadata is analysis state, not a successful fresh catalog.
    if not collection.get('analysis') and collection.get('status') == 'partial':
        clock = collection.get('completed_at') or collection.get('started_at') or payload['catalog']['updated_at']
        return current >= datetime.fromisoformat(clock) + timedelta(seconds=RETRY_SECONDS)
    return (current - datetime.fromisoformat(payload['catalog']['updated_at'])).total_seconds() >= 3600


class SnapshotCheckpoint:
    def __init__(self, path, collection=None, checkpoint=None):
        self.path, self.collection = path, collection
        self.checkpoint = checkpoint_path(checkpoint)
        self.last_written = time.monotonic()

    def __call__(self, progress):
        if self.collection is not None:
            self.collection['results'] = progress.copy()
        if time.monotonic() - self.last_written >= 60:
            write_snapshot(self.path, self.collection, checkpoint=self.checkpoint)
            self.last_written = time.monotonic()


class CatalogCheckpoint:
    def __init__(self, path, checkpoint, collection):
        self.path, self.checkpoint, self.collection = path, checkpoint, collection
        self.last_written = time.monotonic()

    def __call__(self, candidate):
        if time.monotonic() - self.last_written < 60:
            return
        metadata = copy.deepcopy(self.collection)
        metadata['catalog'] = catalog_phase(candidate)
        metadata['status'] = combined_status(metadata)
        write_snapshot(self.path, metadata, catalog=candidate, checkpoint=self.checkpoint, update_db=True)
        self.last_written = time.monotonic()


def finish_collection(collection, matches, stop):
    results = collection.get('results', {})
    analytics = analysis_status(matches)
    remaining = max(0, results.get('total', 0) - results.get('updated', 0) - results.get('failed', 0))
    partial = bool(remaining or results.get('failed', 0) or analytics['pending_teams']
                   or analytics['failed_teams'] or analytics['stale_teams'] or collection.get('error'))
    completed = now_iso()
    budget_exhausted = stop.is_set() or bool(results.get('budget_exhausted'))
    partial = partial or budget_exhausted
    failures = copy.deepcopy(collection.get('analysis', {}).get('failures', []))
    if budget_exhausted and not any(f.get('reason') == 'budget_exceeded' for f in failures):
        failures.append({'kind': 'analysis', 'id': 'collector', 'reason': 'budget_exceeded'})
    phase = {'status': 'partial' if partial else 'completed',
             'catalog_generation': collection['catalog']['catalog_generation'],
             'started_at': collection.get('analysis', {}).get('started_at', collection['started_at']),
             'completed_at': completed,
             'budget_exhausted': budget_exhausted, 'results': copy.deepcopy(results),
             'remaining_teams': remaining, 'analytics': analytics,
             'failures': failures,
             'next_retry_at': ((datetime.fromisoformat(completed) + timedelta(seconds=RETRY_SECONDS)).isoformat()
                               if partial else None)}
    if collection.get('error'):
        phase['error'] = collection['error']
    collection.update(analysis=phase, status=combined_status(collection, phase['status']),
                      completed_at=completed,
                      budget_exhausted=budget_exhausted or collection['catalog'].get('budget_exhausted', False),
                      remaining_teams=remaining, analytics=analytics)


def finalize_file(output, previous, checkpoint, stage, exit_code):
    """Annotate the last validated file without trusting an uncommitted DB catalog."""
    payload = recover_snapshot(output, previous, checkpoint)
    collection = copy.deepcopy(payload.get('collection', {}))
    collection.setdefault('catalog', catalog_phase(payload['catalog']))
    phase = copy.deepcopy(collection.get(stage, {}))
    phase.update(catalog_generation=payload['catalog']['generation'],
                 completed_at=now_iso(), budget_exhausted=exit_code == 124)
    phase.setdefault('started_at', phase['completed_at'])
    reason = 'budget_exceeded' if exit_code == 124 else 'process_error'
    phase.setdefault('failures', []).append({'kind': stage, 'id': 'collector', 'reason': reason,
                                            'exit_code': exit_code})
    phase['next_retry_at'] = (datetime.fromisoformat(phase['completed_at']) + timedelta(seconds=RETRY_SECONDS)).isoformat()
    if stage == 'catalog':
        previous_generation = collection.get('previous_catalog_generation')
        phase['status'] = ('retained_previous' if phase.get('status') == 'retained_previous'
                           or previous_generation == payload['catalog']['generation'] else 'partial')
        payload['catalog'] = set_catalog_phase(payload['catalog'], phase)
    else:
        phase['status'] = 'partial'
    collection[stage] = phase
    collection.update(status=combined_status(collection, collection.get('analysis', {}).get('status')),
                      completed_at=phase['completed_at'],
                      budget_exhausted=any(collection.get(s, {}).get('budget_exhausted') for s in ('catalog', 'analysis')))
    if exit_code not in (0, 124):
        collection['error'] = 'collector_process_error'
    write_snapshot(output, collection, catalog=payload['catalog'], checkpoint=checkpoint, update_db=True)


def positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Time budget must be a positive number')
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('Time budget must be a positive number')
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--check-due', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--catalog-only', action='store_true')
    mode.add_argument('--analysis-only', action='store_true')
    mode.add_argument('--recover-only', action='store_true')
    mode.add_argument('--finalize-interrupted', action='store_true')
    parser.add_argument('--stage', choices=['catalog', 'analysis'])
    parser.add_argument('--exit-code', type=int, default=124)
    parser.add_argument('--catalog-max-seconds', type=positive_seconds, default=600)
    parser.add_argument('--max-seconds', type=positive_seconds, default=2400)
    args = parser.parse_args()
    if args.check_due:
        print('true' if collection_due(args.previous) else 'false')
        return
    if not args.output:
        parser.error('--output is required when collecting data')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    init_db()
    checkpoint = checkpoint_path(args.checkpoint)
    if args.finalize_interrupted:
        if not args.stage:
            parser.error('--stage is required with --finalize-interrupted')
        finalize_file(args.output, args.previous, checkpoint, args.stage, args.exit_code)
        return
    baseline = recover_snapshot(args.output, args.previous, checkpoint)
    if args.recover_only:
        return
    payload = baseline['catalog']
    started = now_iso()
    collection = {'status': 'running', 'started_at': started, 'completed_at': None,
                  'mode': 'analysis_only' if args.analysis_only else 'catalog_only' if args.catalog_only else 'full',
                  'previous_catalog_generation': payload['generation'],
                  'catalog': catalog_phase(payload)}
    from app.scraper.http import set_collection_deadline
    if not args.analysis_only:
        pending = {'status': 'retained_previous', 'catalog_generation': payload['generation'],
                   'started_at': started, 'completed_at': None, 'budget_exhausted': False,
                   'failures': [], 'next_retry_at': (datetime.now(timezone.utc) + timedelta(seconds=RETRY_SECONDS)).isoformat()}
        write_snapshot(args.output, {**collection, 'catalog': pending, 'status': 'retained_previous'},
                       catalog=set_catalog_phase(payload, pending), checkpoint=checkpoint)
        set_collection_deadline(args.catalog_max_seconds)
        try:
            payload = build_snapshot(payload, on_checkpoint=CatalogCheckpoint(args.output, checkpoint, collection))
        finally:
            set_collection_deadline(None)
        collection['catalog'] = catalog_phase(payload)
        collection['status'] = combined_status(collection)
        write_snapshot(args.output, collection, catalog=payload, checkpoint=checkpoint, update_db=True)
    if args.catalog_only or collection['catalog']['status'] in ('retained_previous', 'failed'):
        collection['analysis'] = {'status': 'skipped', 'catalog_generation': payload['generation'],
                                  'started_at': None, 'completed_at': now_iso(), 'budget_exhausted': False,
                                  'failures': [], 'reason': 'catalog_only' if args.catalog_only else 'retained_previous'}
        collection.update(status='catalog_only' if collection['catalog']['status'] == 'completed'
                          else collection['catalog']['status'], completed_at=now_iso(),
                          analytics=analysis_status(payload['matches']))
        write_snapshot(args.output, collection, catalog=payload, checkpoint=checkpoint)
        return
    stop = Event()
    collection['analysis'] = {'status': 'running', 'catalog_generation': payload['generation'],
                              'started_at': now_iso(), 'completed_at': None,
                              'budget_exhausted': False, 'failures': []}
    write_snapshot(args.output, collection, catalog=payload, checkpoint=checkpoint)
    timer = Timer(args.max_seconds, stop.set)
    timer.daemon = True
    set_collection_deadline(args.max_seconds)
    timer.start()
    try:
        collection['results'] = refresh_analysis(payload['matches'], force=False, stop=stop,
                                                on_progress=SnapshotCheckpoint(args.output, collection, checkpoint))
    except Exception as exc:
        collection['error'] = type(exc).__name__
        collection['analysis']['failures'].append({'kind': 'analysis', 'id': 'collector', 'reason': 'process_error'})
        raise
    finally:
        timer.cancel()
        timer.join()
        set_collection_deadline(None)
        finish_collection(collection, payload['matches'], stop)
        write_snapshot(args.output, collection, catalog=payload, checkpoint=checkpoint)
    logger.info('Catalog %s; collection %s', payload['generation'], collection['status'])


if __name__ == '__main__':
    main()
