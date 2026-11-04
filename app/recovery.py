"""Bounded background recovery while a snapshot-backed server is awake.

The public GitHub feed remains the durable store. Recovery owns a separate
collector database and installs only verified files into the serving database.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
import threading

from app import db, snapshot_feed
from app.collector_runner import supervise, validate_publishable
from app.sync_lease import sync_lease

logger = logging.getLogger(__name__)
STALE_SECONDS = 75 * 60
RETRY_SECONDS = 15 * 60
STAGE_SECONDS = {'catalog': 660, 'analysis': 1230}
STATUS_KEY = 'local_recovery'
_lock = threading.Lock()
_worker = None
_stop = threading.Event()


def now():
    return datetime.now(timezone.utc)


def get_status():
    """Read recovery state without scheduling work or changing any clocks."""
    conn = db.get_db_connection()
    try:
        row = conn.execute('SELECT details_json FROM sync_meta WHERE key=?', (STATUS_KEY,)).fetchone()
        return json.loads(row[0]) if row else {'status': 'idle'}
    finally:
        conn.close()


def _save_status(status):
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute('INSERT INTO sync_meta(key,last_synced_at,status,details_json) VALUES(?,?,?,?) '
                         'ON CONFLICT(key) DO UPDATE SET last_synced_at=excluded.last_synced_at, '
                         'status=excluded.status, details_json=excluded.details_json',
                         (STATUS_KEY, now().isoformat(), status['status'], json.dumps(status)))
    finally:
        conn.close()


def _aged(timestamp, current):
    try:
        age = (current - datetime.fromisoformat(timestamp)).total_seconds()
        return age < 0 or age >= STALE_SECONDS
    except (TypeError, ValueError):
        return True


def _needs_recovery(catalog, current=None):
    from app.analysis import requirements, own_event_requirements, SCHEMA_VERSION
    current = current or now()
    if not catalog or not catalog.get('ready_count'):
        return True, True
    catalog_due = _aged(catalog.get('updated_at'), current)
    matches = catalog.get('matches', [])
    required = requirements(matches)
    owned_events = own_event_requirements(matches)
    teams = db.get_analysis_teams(required)
    for tid, events in required.items():
        team = teams.get(tid, {})
        available = set(map(str, team.get('available_events', [])))
        # A newly discovered OWN event needs a refreshed overview even when the
        # prior scopes are young. Opponent-only menus do not prove participation.
        if owned_events.get(tid, set()) - available:
            return catalog_due, True
        keys = (set(map(str, events)) & available) | {'all'}
        if team.get('schema_version') != SCHEMA_VERSION or any(
                _aged(team.get('scopes', {}).get(key, {}).get('collected_at'), current) for key in keys):
            return catalog_due, True
    return catalog_due, False


def _cooling(status, current=None):
    try:
        return (current or now()) < datetime.fromisoformat(status['next_retry_at'])
    except (KeyError, TypeError, ValueError):
        return False


def start():
    """Reset shutdown state for a new application lifespan, after the old worker exits."""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return False
        _worker = None
        _stop.clear()
        return True


def maybe_start():
    """Enqueue at most one recovery; HTTP readers never call the collector."""
    global _worker
    if not snapshot_feed.enabled() or os.environ.get('VLR_LOCAL_RECOVERY', '1').lower() in {'0', 'false', 'off'}:
        return False
    with _lock:
        if _stop.is_set() or (_worker is not None and _worker.is_alive()):
            return False
        if _cooling(get_status()) or not any(_needs_recovery(db.get_catalog_snapshot())):
            return False
        _worker = threading.Thread(target=_recover, daemon=True, name='VLRLocalRecovery')
        _worker.start()
        return True


class RecoveryStopped(Exception):
    pass


def _run_stage(stage, directory, env):
    output, previous = directory / 'snapshot.json', directory / 'previous.json'
    command = [sys.executable, '-m', 'app.recovery_worker', '--output', str(output),
               '--previous', str(previous)]
    hard = STAGE_SECONDS[stage]
    command += (['--catalog-only', '--catalog-max-seconds', str(hard - 60)] if stage == 'catalog'
                else ['--analysis-only', '--max-seconds', str(hard - 60)])
    code = supervise(command, hard_seconds=hard, grace_seconds=60, env=env, stop_event=_stop)
    if code == 130 or _stop.is_set():
        raise RecoveryStopped()
    if code:
        finalize = [sys.executable, '-m', 'app.recovery_worker', '--output', str(output),
                    '--previous', str(previous), '--finalize-interrupted', '--stage', stage,
                    '--exit-code', str(code)]
        final_code = supervise(finalize, hard_seconds=30, grace_seconds=2, env=env, stop_event=_stop)
        if final_code == 130 or _stop.is_set():
            raise RecoveryStopped()
        if final_code:
            raise RuntimeError('Recovery checkpoint finalization failed')
    payload = validate_publishable(json.loads(output.read_text(encoding='utf-8')))
    return payload, code


def _install(payload, baseline, state):
    payload = copy.deepcopy(payload)
    if datetime.fromisoformat(payload['catalog']['updated_at']) > datetime.fromisoformat(baseline['catalog']['updated_at']):
        payload['catalog']['data_origin'] = 'render_recovery'
    snapshot_feed.install(payload)
    # The external feed may have advanced during collection. Its newer catalog
    # wins; phase metadata must continue to identify our own candidate generation.
    state.update(catalog_generation=payload['catalog']['generation'],
                 collection=copy.deepcopy(payload.get('collection', {})),
                 installed_generation=(db.get_catalog_snapshot() or {}).get('generation'))
    _save_status(state)


def _recover():
    from app.snapshot_export import make_payload, atomic_write
    with sync_lease(STATUS_KEY) as acquired:
        if not acquired or _stop.is_set() or _cooling(get_status()):
            return
        catalog = db.get_catalog_snapshot()
        catalog_due, analysis_due = _needs_recovery(catalog)
        if not catalog_due and not analysis_due:
            return
        state = {'status': 'running', 'started_at': now().isoformat(), 'completed_at': None,
                 'next_retry_at': (now() + timedelta(seconds=RETRY_SECONDS)).isoformat(),
                 'catalog_generation': (catalog or {}).get('generation'), 'collection': {}, 'last_error': None}
        _save_status(state)
        try:
            # Do not let file-first collector recovery ever restore the live DB.
            directory = Path(db.DB_DIR).resolve() / 'recovery'
            directory.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, VLR_DATA_DIR=str(directory), VLR_REFRESH_MODE='local',
                       VLR_REQUEST_INTERVAL_SECONDS='1.0', VLR_COLLECTION_WORKERS='1',
                       MALLOC_ARENA_MAX='2')
            baseline = make_payload(catalog=catalog)
            atomic_write(directory / 'previous.json', baseline)
            payload, code = baseline, 0
            if catalog_due:
                payload, code = _run_stage('catalog', directory, env)
                _install(payload, baseline, state)
                phase = payload['catalog'].get('collection', {})
                if code not in (0, 124) or phase.get('status') in {'retained_previous', 'failed'}:
                    raise RuntimeError('Catalog recovery did not produce a new usable generation')
            if not _stop.is_set():
                # A new catalog can contain teams that were not in the old one.
                payload, code = _run_stage('analysis', directory, env)
                _install(payload, baseline, state)
                if code not in (0, 124):
                    raise RuntimeError('Analysis recovery process failed')
            else:
                raise RecoveryStopped()
            collection = payload.get('collection', {})
            state['status'] = ('partial' if code or collection.get('status') in
                               {'partial', 'failed', 'retained_previous'} else 'completed')
        except RecoveryStopped:
            state.update(status='interrupted', last_error='server_stopping')
        except Exception as exc:
            logger.exception('Local recovery failed; verified serving data remains available')
            state.update(status='failed', last_error=type(exc).__name__)
        finally:
            state.update(completed_at=now().isoformat(),
                         next_retry_at=(now() + timedelta(seconds=RETRY_SECONDS)).isoformat())
            _save_status(state)


def stop():
    """Abort the isolated child promptly when the web service shuts down."""
    _stop.set()
    with _lock:
        worker = _worker
    if worker is not None:
        worker.join(timeout=5)
