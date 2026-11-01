import copy
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from app import catalog, db, snapshot_export as export, snapshot_feed as feed


def bundle(generation='old', age=120):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    team = {'schema_version': 3, 'updated_at': stamp, 'last_attempt_at': stamp,
            'last_success_at': stamp, 'last_error': None, 'available_events': [],
            'failed_scopes': [], 'scopes': {'all': {'collected_at': stamp, 'maps': {}, 'players': {}}}}
    return {'schema_version': 1, 'published_at': stamp,
            'catalog': {'schema_version': 1, 'generation': generation,
                        'updated_at': (now - timedelta(minutes=age)).isoformat(),
                        'ready_count': 1, 'pending_count': 0, 'failures': [],
                        'matches': [{'id': '123', 'selection_status': 'ready', 'selection_data': {
                            'details': {'team_a_id': '1', 'team_b_id': '2', 'event_id': '20'},
                            'team_a_events': [], 'team_b_events': []}}]},
            'analysis': {'schema_version': 3, 'teams': {'1': copy.deepcopy(team), '2': copy.deepcopy(team)}}}


def phase_bundle(status='partial', generation='new', age=30):
    payload = bundle(generation, age)
    now = datetime.now(timezone.utc)
    phase = {'status': status, 'catalog_generation': generation,
             'started_at': now.isoformat(), 'completed_at': now.isoformat(),
             'budget_exhausted': status == 'partial',
             'failures': [{'kind': 'pool', 'id': '20', 'reason': 'budget_exceeded'}] if status == 'partial' else [],
             'next_retry_at': (now + timedelta(minutes=15)).isoformat() if status != 'completed' else None}
    payload['catalog']['collection'] = copy.deepcopy(phase)
    payload['collection'] = {'status': status, 'catalog': phase, 'mode': 'catalog_only'}
    return payload


def write(path, payload):
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def install(payload):
    db.restore_collector_snapshot(payload['catalog'], payload['analysis']['teams'])


@pytest.mark.parametrize('fault', ['validation', 'write', 'replace'])
def test_candidate_failure_preserves_both_files_and_database(tmp_path, monkeypatch, fault):
    old, new = bundle(), bundle('new', 0)
    install(old)
    output, checkpoint = write(tmp_path / 'public.json', old), write(tmp_path / 'durable.json', old)
    if fault == 'validation':
        new['catalog']['ready_count'] = 9
    elif fault == 'write':
        original = Path.write_text
        def fail(path, *args, **kwargs):
            if path == checkpoint.with_suffix('.tmp'):
                raise OSError('disk full')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'write_text', fail)
    else:
        original = Path.replace
        def fail(path, *args, **kwargs):
            if path == checkpoint.with_suffix('.tmp'):
                raise OSError('replacement denied')
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises((OSError, ValueError)):
        export.write_snapshot(output, catalog=new['catalog'], checkpoint=checkpoint, update_db=True)
    assert json.loads(output.read_text()) == old
    assert json.loads(checkpoint.read_text()) == old
    assert db.get_catalog_snapshot() == old['catalog']


def test_output_failure_after_checkpoint_replacement_resumes_from_durable_file(tmp_path, monkeypatch):
    old, new = bundle(), bundle('new', 0)
    install(old)
    output, checkpoint = write(tmp_path / 'public.json', old), write(tmp_path / 'durable.json', old)
    original = Path.replace
    with monkeypatch.context() as scoped:
        def fail(path, *args, **kwargs):
            if path == output.with_suffix('.tmp'):
                raise OSError('output replacement denied')
            return original(path, *args, **kwargs)
        scoped.setattr(Path, 'replace', fail)
        with pytest.raises(OSError):
            export.write_snapshot(output, catalog=new['catalog'], checkpoint=checkpoint, update_db=True)
    assert json.loads(output.read_text())['catalog']['generation'] == 'old'
    assert json.loads(checkpoint.read_text())['catalog']['generation'] == 'new'
    assert db.get_catalog_snapshot()['generation'] == 'old'
    recovered = export.recover_snapshot(output, checkpoint=checkpoint)
    assert recovered['catalog']['generation'] == db.get_catalog_snapshot()['generation'] == 'new'


def test_database_failure_after_file_commit_keeps_candidate_for_restart(tmp_path, monkeypatch):
    old, new = bundle(), bundle('new', 0)
    install(old)
    output, checkpoint = write(tmp_path / 'public.json', old), write(tmp_path / 'durable.json', old)
    monkeypatch.setattr(export, 'save_catalog_snapshot', Mock(side_effect=sqlite3.OperationalError('locked')))
    with pytest.raises(sqlite3.OperationalError):
        export.write_snapshot(output, catalog=new['catalog'], checkpoint=checkpoint, update_db=True)
    assert db.get_catalog_snapshot()['generation'] == 'old'
    assert feed.validate(json.loads(checkpoint.read_text()))['catalog']['generation'] == 'new'
    export.recover_snapshot(output, checkpoint=checkpoint)
    assert db.get_catalog_snapshot()['generation'] == 'new'


def test_unverified_newer_database_catalog_never_becomes_recovery_authority(tmp_path):
    public, ghost = bundle(), bundle('unvalidated-database', 0)
    install(ghost)
    previous = write(tmp_path / 'published.json', public)
    recovered = export.recover_snapshot(tmp_path / 'output.json', previous, tmp_path / 'checkpoint.json')
    assert recovered['catalog']['generation'] == 'old'
    assert db.get_catalog_snapshot()['generation'] == 'old'


def test_newer_local_checkpoint_beats_remote_and_preserves_newer_analysis_scopes(tmp_path):
    remote, local = bundle(), bundle('local', 15)
    install(remote)
    newer = copy.deepcopy(remote['analysis']['teams']['1'])
    newer['scopes']['all'].update(collected_at=datetime.now(timezone.utc).isoformat(),
                                  maps={'Bind': {'played': 4, 'w': 3, 'l': 1}})
    db.save_analysis_team('1', newer)
    previous = write(tmp_path / 'published.json', remote)
    checkpoint = write(tmp_path / 'checkpoint.json', local)
    recovered = export.recover_snapshot(tmp_path / 'output.json', previous, checkpoint)
    assert recovered['catalog']['generation'] == 'local'
    assert recovered['analysis']['teams']['1']['scopes']['all'] == newer['scopes']['all']
    assert db.get_analysis_teams()['1']['scopes']['all'] == newer['scopes']['all']


def test_invalid_checkpoint_generation_cannot_displace_valid_public_file(tmp_path):
    remote, corrupt = bundle(), phase_bundle()
    corrupt['collection']['catalog']['catalog_generation'] = 'wrong-generation'
    previous = write(tmp_path / 'published.json', remote)
    checkpoint = write(tmp_path / 'checkpoint.json', corrupt)
    recovered = export.recover_snapshot(tmp_path / 'output.json', previous, checkpoint)
    assert recovered['catalog']['generation'] == 'old'
    assert json.loads(checkpoint.read_text())['catalog']['generation'] == 'old'


def test_no_valid_previous_or_seed_cannot_publish_empty_first_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(export, 'seed_payload', lambda: None)
    output = tmp_path / 'output.json'
    with pytest.raises(ValueError, match='No validated'):
        export.recover_snapshot(output, checkpoint=tmp_path / 'checkpoint.json')
    assert not output.exists() and db.get_catalog_snapshot() is None


def test_analysis_only_preserves_partial_catalog_generation_and_failure_reason(tmp_path, monkeypatch):
    partial = phase_bundle()
    previous = write(tmp_path / 'published.json', partial)
    output = tmp_path / 'output.json'
    monkeypatch.setattr(sys, 'argv', ['export', '--analysis-only', '--previous', str(previous),
                                    '--output', str(output)])
    monkeypatch.setattr(export, 'refresh_analysis', lambda *args, **kwargs: {'updated': 2, 'failed': 0, 'total': 2})
    export.main()
    result = feed.validate(json.loads(output.read_text()))
    assert result['collection']['analysis']['status'] == 'completed'
    assert result['collection']['catalog'] == partial['collection']['catalog']
    assert result['collection']['status'] == 'partial'
    assert result['catalog']['generation'] == 'new'


def test_failed_attempt_retries_in_fifteen_minutes_and_success_restores_hourly_clock(tmp_path, monkeypatch):
    partial = phase_bundle()
    previous = write(tmp_path / 'published.json', partial)
    retry = datetime.fromisoformat(partial['collection']['catalog']['next_retry_at'])
    assert not export.collection_due(previous, now=retry - timedelta(seconds=1))
    assert export.collection_due(previous, now=retry)
    success = phase_bundle('completed', 'recovered', 0)
    monkeypatch.setattr(export, 'build_snapshot', lambda *args, **kwargs: success['catalog'])
    output = tmp_path / 'output.json'
    monkeypatch.setattr(sys, 'argv', ['export', '--catalog-only', '--previous', str(previous), '--output', str(output)])
    export.main()
    final = feed.validate(json.loads(output.read_text()))
    phase = final['collection']['catalog']
    assert phase['status'] == 'completed' and phase['failures'] == []
    assert not phase['budget_exhausted'] and phase['next_retry_at'] is None
    updated = datetime.fromisoformat(final['catalog']['updated_at'])
    assert not export.collection_due(output, now=updated + timedelta(seconds=3599))
    assert export.collection_due(output, now=updated + timedelta(seconds=3600))


def test_same_generation_older_failed_phase_does_not_undo_installed_success(monkeypatch):
    old = phase_bundle()
    fresh = copy.deepcopy(old)
    fresh_phase = fresh['catalog']['collection']
    fresh_phase.update(status='completed', completed_at=datetime.now(timezone.utc).isoformat(),
                       budget_exhausted=False, failures=[], next_retry_at=None)
    fresh['collection']['catalog'] = copy.deepcopy(fresh_phase)
    feed.install(fresh)
    monkeypatch.setattr(feed, 'download', lambda: old)
    imported = feed.refresh()
    assert imported['collection']['catalog']['status'] == 'completed'
    assert db.get_catalog_snapshot()['collection']['status'] == 'completed'


def test_timeout_finalization_retains_old_data_clock_and_records_fifteen_minute_retry(tmp_path):
    retained = phase_bundle('retained_previous', 'old')
    retained['collection']['previous_catalog_generation'] = 'old'
    output = write(tmp_path / 'output.json', retained)
    checkpoint = write(tmp_path / 'checkpoint.json', retained)
    original_clock = retained['catalog']['updated_at']
    export.finalize_file(output, None, checkpoint, 'catalog', 124)
    final = feed.validate(json.loads(output.read_text()))
    phase = final['collection']['catalog']
    assert final['catalog']['updated_at'] == original_clock
    assert phase['status'] == 'retained_previous' and phase['budget_exhausted']
    assert phase['failures'][-1]['reason'] == 'budget_exceeded'
    assert datetime.fromisoformat(phase['next_retry_at']) - datetime.fromisoformat(phase['completed_at']) == timedelta(minutes=15)


def test_catalog_checkpoints_validate_complete_candidates_and_limit_write_frequency(tmp_path, monkeypatch):
    old = bundle()
    install(old)
    output, checkpoint = write(tmp_path / 'output.json', old), write(tmp_path / 'checkpoint.json', old)
    clock = [0]
    monkeypatch.setattr(export.time, 'monotonic', lambda: clock[0])
    collection = {'status': 'running', 'catalog': export.catalog_phase(old['catalog'])}
    save = export.CatalogCheckpoint(output, checkpoint, collection)
    candidate = phase_bundle(generation='candidate')['catalog']
    candidate['matches'].append({'id': '456', 'selection_status': 'pending'})
    candidate['pending_count'] = 1
    clock[0] = 59
    save(candidate)
    assert json.loads(checkpoint.read_text()) == old
    incomplete = copy.deepcopy(candidate)
    del incomplete['matches'][0]['selection_data']['details']['team_b_id']
    clock[0] = 60
    with pytest.raises((ValueError, KeyError)):
        save(incomplete)
    assert json.loads(checkpoint.read_text()) == old
    assert db.get_catalog_snapshot() == old['catalog']
    save(candidate)
    result = feed.validate(json.loads(checkpoint.read_text()))
    assert result['catalog']['ready_count'] == 1
    assert result['catalog']['matches'][1]['selection_status'] == 'pending'
    assert 'selection_data' not in result['catalog']['matches'][1]
    assert db.get_catalog_snapshot() == candidate
    updated = copy.deepcopy(candidate)
    updated['matches'][0]['team_a'] = 'Updated name'
    clock[0] = 119
    save(updated)
    assert json.loads(checkpoint.read_text()) == result
    # Final output is mandatory even when the periodic checkpoint is throttled.
    export.write_snapshot(output, collection, catalog=updated, checkpoint=checkpoint, update_db=True)
    assert json.loads(output.read_text())['catalog']['matches'][0]['team_a'] == 'Updated name'
    assert json.loads(checkpoint.read_text()) == json.loads(output.read_text())


@pytest.mark.parametrize('stop_set', [False, True])
def test_analysis_budget_cause_always_produces_partial_retryable_phase(monkeypatch, stop_set):
    payload = phase_bundle('completed')
    collection = {'started_at': export.now_iso(), 'catalog': payload['catalog']['collection'],
                  'results': {'updated': 2, 'failed': 0, 'total': 2, 'budget_exhausted': not stop_set}}
    monkeypatch.setattr(export, 'analysis_status', lambda _: {
        'pending_teams': 0, 'failed_teams': 0, 'stale_teams': 0})
    stop = Event()
    if stop_set:
        stop.set()
    export.finish_collection(collection, payload['catalog']['matches'], stop)
    phase = collection['analysis']
    assert collection['status'] == phase['status'] == 'partial'
    assert phase['budget_exhausted']
    assert phase['failures'] == [{'kind': 'analysis', 'id': 'collector', 'reason': 'budget_exceeded'}]
    assert datetime.fromisoformat(phase['next_retry_at']) - datetime.fromisoformat(phase['completed_at']) == timedelta(minutes=15)
