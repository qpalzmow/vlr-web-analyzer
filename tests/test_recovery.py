"""Recovery remains bounded, isolated from serving data, and safe during feed races."""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from threading import Event, Thread
import time

import pytest

from app import db, recovery, snapshot_feed
from app import collector_runner as runner
from app.sync_lease import sync_lease


def payload(age=0, generation='baseline'):
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    return {'schema_version': 1, 'published_at': stamp,
            'catalog': {'schema_version': 1, 'generation': generation, 'updated_at': stamp,
                        'ready_count': 1, 'matches': [{'id': '123', 'selection_status': 'ready',
                            'selection_data': {'details': {'team_a_id': '1', 'team_b_id': '2'},
                                               'team_a_events': [{'id': '20', 'name': 'Event'}],
                                               'team_b_events': []}}]},
            'analysis': {'schema_version': 3, 'teams': {
                tid: {'schema_version': 3, 'updated_at': stamp, 'last_attempt_at': stamp,
                      'available_events': ['20'], 'scopes': {
                          key: {'collected_at': stamp, 'maps': {}, 'players': {}}
                          for key in ('all', '20')}} for tid in ('1', '2')}}}


def phase(data, stage, status='completed'):
    generation = data['catalog']['generation']
    stamp = datetime.now(timezone.utc).isoformat()
    metadata = {'status': status, 'catalog_generation': generation,
                'started_at': stamp, 'completed_at': stamp, 'failures': [],
                'budget_exhausted': status == 'partial'}
    if stage == 'catalog':
        data['catalog']['collection'] = metadata
    data.setdefault('collection', {})[stage] = metadata
    data['collection']['status'] = status
    return data


@pytest.fixture(autouse=True)
def isolated_recovery(monkeypatch):
    monkeypatch.setattr(recovery, '_worker', None)
    monkeypatch.setattr(recovery, '_stop', Event())
    monkeypatch.setenv('VLR_REFRESH_MODE', 'snapshot')
    monkeypatch.delenv('VLR_LOCAL_RECOVERY', raising=False)
    yield
    recovery.stop()


def test_fresh_catalog_and_all_required_scopes_do_not_schedule(monkeypatch):
    data = payload()
    snapshot_feed.install(data)
    monkeypatch.setattr(recovery, '_recover', lambda: pytest.fail('Fresh data must not start collection'))
    assert recovery._needs_recovery(data['catalog']) == (False, False)
    assert not recovery.maybe_start()
    assert recovery.get_status() == {'status': 'idle'}


def test_analysis_age_is_independent_of_new_catalog_and_attempt_clock():
    data = payload()
    data['analysis']['teams']['1']['scopes']['20']['collected_at'] = (
        datetime.now(timezone.utc) - timedelta(minutes=80)).isoformat()
    snapshot_feed.install(data)
    assert recovery._needs_recovery(data['catalog']) == (False, True)
    data['analysis']['teams']['1']['scopes'].pop('20')
    db.save_analysis_team('1', data['analysis']['teams']['1'])
    assert recovery._needs_recovery(data['catalog']) == (False, True)


def test_missing_analysis_team_triggers_recovery_with_fresh_catalog():
    data = payload()
    del data['analysis']['teams']['2']
    snapshot_feed.install(data)
    assert recovery._needs_recovery(data['catalog']) == (False, True)


def test_new_owned_event_triggers_recovery_before_existing_scopes_expire():
    data = payload()
    data['catalog']['matches'][0]['selection_data']['team_a_events'].append({'id': '21', 'name': 'New Cup'})
    snapshot_feed.install(data)
    assert recovery._needs_recovery(data['catalog']) == (False, True)


def test_opponents_new_event_does_not_make_other_team_pending():
    data = payload()
    selection = data['catalog']['matches'][0]['selection_data']
    selection['team_b_events'] = [{'id': '21', 'name': 'Opponent-only Cup'}]
    team_b = data['analysis']['teams']['2']
    team_b['available_events'].append('21')
    team_b['scopes']['21'] = copy.deepcopy(team_b['scopes']['20'])
    snapshot_feed.install(data)
    assert recovery._needs_recovery(data['catalog']) == (False, False)


def test_due_boundary_uses_real_collection_clock():
    data = payload()
    snapshot_feed.install(data)
    # Capture the comparison clock after constructing the scopes: Linux can
    # resolve microseconds that Windows rounds to the same clock tick.
    current = datetime.now(timezone.utc)
    data['catalog']['updated_at'] = (current - timedelta(seconds=4499)).isoformat()
    assert recovery._needs_recovery(data['catalog'], current) == (False, False)
    data['catalog']['updated_at'] = (current - timedelta(seconds=4500)).isoformat()
    assert recovery._needs_recovery(data['catalog'], current) == (True, False)


@pytest.mark.parametrize('disabled', ['0', 'false', 'off'])
def test_explicitly_disabled_recovery_cannot_start(monkeypatch, disabled):
    snapshot_feed.install(payload(age=8000))
    monkeypatch.setenv('VLR_LOCAL_RECOVERY', disabled)
    assert not recovery.maybe_start()


def test_maybe_start_is_nonblocking_singleflight_and_restartable(monkeypatch):
    snapshot_feed.install(payload(age=8000))
    entered, release = Event(), Event()
    calls = []
    def blocked():
        calls.append(1)
        entered.set()
        release.wait(3)
    monkeypatch.setattr(recovery, '_recover', blocked)
    started = time.monotonic()
    try:
        assert recovery.maybe_start()
        assert time.monotonic() - started < 1
        assert entered.wait(1)
        assert not recovery.maybe_start()
        assert not recovery.start(), 'Do not reset cancellation while old worker is alive'
        assert len(calls) == 1
    finally:
        release.set()
        recovery.stop()
    assert not recovery.maybe_start(), 'A stopped lifespan cannot restart itself'
    assert recovery.start()
    assert recovery.maybe_start()


def test_cooldown_is_persisted_and_survives_module_worker_reset(monkeypatch):
    snapshot_feed.install(payload(age=8000))
    recovery._save_status({'status': 'failed', 'next_retry_at': (
        datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()})
    recovery.start()
    assert not recovery.maybe_start()
    monkeypatch.setattr(recovery, '_run_stage', lambda *_: pytest.fail('Cooldown must block another process too'))
    recovery._recover()
    assert recovery.get_status()['status'] == 'failed'


def test_named_recovery_lease_does_not_block_external_feed_lease():
    with sync_lease(recovery.STATUS_KEY) as recovery_owner:
        assert recovery_owner
        with sync_lease() as feed_owner:
            assert feed_owner
        with sync_lease(recovery.STATUS_KEY) as duplicate:
            assert not duplicate
    with sync_lease(recovery.STATUS_KEY) as released:
        assert released


def test_catalog_then_analysis_uses_isolated_db_and_installs_each_stage(monkeypatch, tmp_path):
    baseline = payload(age=8000)
    snapshot_feed.install(baseline)
    fresh = phase(payload(generation='local-new'), 'catalog')
    observed = []
    def stage(kind, directory, env):
        assert Path(env['VLR_DATA_DIR']) == tmp_path / 'recovery'
        assert env['VLR_DATA_DIR'] != db.DB_DIR
        assert env['VLR_REFRESH_MODE'] == 'local'
        assert env['VLR_REQUEST_INTERVAL_SECONDS'] == '1.0'
        assert json.loads((directory / 'previous.json').read_text())['catalog'] == baseline['catalog']
        observed.append(kind)
        if kind == 'catalog':
            assert db.get_catalog_snapshot()['generation'] == 'baseline'
            return copy.deepcopy(fresh), 0
        assert db.get_catalog_snapshot()['generation'] == 'local-new'
        return phase(copy.deepcopy(fresh), 'analysis'), 0
    monkeypatch.setattr(recovery, '_run_stage', stage)
    recovery._recover()
    assert observed == ['catalog', 'analysis']
    assert db.get_catalog_snapshot()['data_origin'] == 'render_recovery'
    assert recovery.get_status()['status'] == 'completed'
    assert recovery.get_status()['collection']['analysis']['status'] == 'completed'


def test_fresh_catalog_stale_analysis_skips_catalog_stage(monkeypatch):
    baseline = payload()
    baseline['analysis']['teams']['1']['scopes']['all']['collected_at'] = (
        datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    snapshot_feed.install(baseline)
    stages = []
    def stage(kind, *args):
        stages.append(kind)
        result = payload()
        result['catalog'] = copy.deepcopy(baseline['catalog'])
        return phase(result, 'analysis'), 0
    monkeypatch.setattr(recovery, '_run_stage', stage)
    recovery._recover()
    assert stages == ['analysis']
    assert 'data_origin' not in db.get_catalog_snapshot(), 'Analysis alone cannot relabel catalog provenance'


def test_corrupt_child_output_preserves_serving_data_and_sets_retry(monkeypatch):
    baseline = payload(age=8000)
    snapshot_feed.install(baseline)
    def fail(*args):
        raise ValueError('Malformed checkpoint')
    monkeypatch.setattr(recovery, '_run_stage', fail)
    recovery._recover()
    assert db.get_catalog_snapshot() == baseline['catalog']
    assert db.get_analysis_teams() == baseline['analysis']['teams']
    state = recovery.get_status()
    assert state['status'] == 'failed'
    assert state['last_error'] == 'ValueError'
    assert datetime.fromisoformat(state['next_retry_at']) > datetime.now(timezone.utc)


def test_retained_previous_catalog_does_not_start_analysis(monkeypatch):
    baseline = payload(age=8000)
    snapshot_feed.install(baseline)
    retained = phase(copy.deepcopy(baseline), 'catalog', 'retained_previous')
    stages = []
    def stage(kind, *args):
        stages.append(kind)
        return retained, 0
    monkeypatch.setattr(recovery, '_run_stage', stage)
    recovery._recover()
    assert stages == ['catalog']
    assert db.get_catalog_snapshot()['updated_at'] == baseline['catalog']['updated_at']
    assert 'data_origin' not in db.get_catalog_snapshot()
    assert recovery.get_status()['status'] == 'failed'


def test_newer_github_generation_wins_race_with_local_install():
    baseline = payload(age=8000)
    candidate = phase(payload(age=100, generation='local'), 'catalog')
    latest = payload(generation='github-latest')
    snapshot_feed.install(baseline)
    snapshot_feed.install(latest)
    state = {'status': 'running'}
    recovery._install(candidate, baseline, state)
    assert db.get_catalog_snapshot() == latest['catalog']
    assert db.get_analysis_teams() == latest['analysis']['teams']
    assert state['catalog_generation'] == 'local'
    assert state['installed_generation'] == 'github-latest'


def test_timeout_finalizes_checkpoint_before_validation(monkeypatch, tmp_path):
    final = phase(payload(), 'analysis', 'partial')
    calls = []
    def supervise(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            (tmp_path / 'snapshot.json').write_text('{unfinished', encoding='utf-8')
            return 124
        (tmp_path / 'snapshot.json').write_text(json.dumps(final), encoding='utf-8')
        return 0
    monkeypatch.setattr(recovery, 'supervise', supervise)
    result, code = recovery._run_stage('analysis', tmp_path, {'VLR_DATA_DIR': 'isolated'})
    assert code == 124
    assert result == final
    assert '--finalize-interrupted' in calls[1][0]
    assert calls[0][1]['hard_seconds'] == 1230
    assert calls[0][1]['stop_event'] is recovery._stop
    assert calls[1][1]['hard_seconds'] == 30


def test_failed_finalization_cannot_install_unsettled_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery, 'supervise', lambda *args, **kwargs: 7)
    with pytest.raises(RuntimeError, match='finalization'):
        recovery._run_stage('catalog', tmp_path, {})


def test_actual_child_reuses_fresh_baseline_in_a_separate_sqlite(tmp_path):
    baseline = payload()
    snapshot_feed.install(baseline)
    directory = tmp_path / 'recovery'
    directory.mkdir()
    (directory / 'previous.json').write_text(json.dumps(baseline), encoding='utf-8')
    # The child must need no HTTP calls for this fully prepared baseline.
    (directory / 'sitecustomize.py').write_text(
        'import socket\n'
        'def forbidden(*args, **kwargs):\n'
        '    raise AssertionError("Fresh scopes must not access the network")\n'
        'socket.socket.connect = forbidden\n', encoding='utf-8')
    env = dict(os.environ, VLR_DATA_DIR=str(directory), VLR_REFRESH_MODE='local',
               PYTHONPATH=str(directory), PYTHONIOENCODING='utf-8')
    result, code = recovery._run_stage('analysis', directory, env)
    assert code == 0
    assert result['collection']['analysis']['status'] == 'completed'
    assert result['collection']['results']['total'] == 0
    assert (directory / 'vlr_analyzer.db').exists()
    assert db.get_catalog_snapshot() == baseline['catalog']
    assert db.get_analysis_teams() == baseline['analysis']['teams']
    assert recovery.get_status() == {'status': 'idle'}


def test_stop_cancels_stage_without_extra_collection_or_finalization(monkeypatch, tmp_path):
    calls = []
    def cancel(*args, **kwargs):
        calls.append(1)
        return 130
    monkeypatch.setattr(recovery, 'supervise', cancel)
    with pytest.raises(recovery.RecoveryStopped):
        recovery._run_stage('catalog', tmp_path, {})
    assert len(calls) == 1


def test_supervisor_stop_reclaims_child_before_its_hard_deadline(tmp_path):
    stop, ready = Event(), tmp_path / 'ready'
    command = [sys.executable, '-c',
               'import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text("ready"); time.sleep(30)', str(ready)]
    result = []
    thread = Thread(target=lambda: result.append(runner.supervise(command, hard_seconds=20,
                    grace_seconds=2, stop_event=stop)), daemon=True)
    thread.start()
    limit = time.monotonic() + 5
    while not ready.exists() and time.monotonic() < limit:
        time.sleep(.02)
    assert ready.exists(), 'Exercise an actually running child'
    start = time.monotonic()
    stop.set()
    thread.join(timeout=4)
    assert result == [130]
    assert time.monotonic() - start < 4
