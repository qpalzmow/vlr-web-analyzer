"""An awake-server collection and an external publication may arrive out of order."""
import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app import catalog, db, recovery


def clock(minutes=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def fixture_data():
    stamp = clock(-20)
    phase = {'status': 'completed', 'catalog_generation': 'local',
             'started_at': stamp, 'completed_at': stamp, 'failures': []}
    snapshot = {'schema_version': 1, 'generation': 'local', 'updated_at': stamp,
                'data_origin': 'render_recovery', 'collection': phase,
                'matches': [], 'ready_count': 0, 'pending_count': 0}
    team = {'schema_version': 3, 'team_id': '1', 'updated_at': stamp,
            'last_attempt_at': stamp, 'last_success_at': stamp, 'last_error': None,
            'available_events': ['10'], 'scopes': {
                'all': {'collected_at': stamp, 'maps': {}, 'players': {}},
                '10': {'collected_at': stamp, 'maps': {'Haven': {'w': 3}}, 'players': {}}}}
    return snapshot, team


def test_later_remote_attempt_keeps_newer_local_scope():
    snapshot, team = fixture_data()
    db.save_catalog_snapshot(snapshot)
    db.save_analysis_team('1', team)
    incoming = copy.deepcopy(team)
    incoming.update(last_attempt_at=clock(-1), updated_at=clock(-1), last_error='scope_collection_failed')
    incoming['scopes']['10'].update(collected_at=clock(-100), maps={'Haven': {'w': 1}})
    incoming['scopes']['all']['collected_at'] = clock(-1)
    db.install_prepared_snapshot(snapshot, {'1': incoming})
    actual = db.get_analysis_teams()['1']
    assert actual['last_error'] == 'scope_collection_failed'
    assert actual['scopes']['10'] == team['scopes']['10']
    assert actual['scopes']['all'] == incoming['scopes']['all']


def test_older_attempt_can_fill_newer_scope_without_reverting_team_metadata():
    snapshot, team = fixture_data()
    team.update(updated_at=clock(-1), last_attempt_at=clock(-1))
    db.save_analysis_team('1', team)
    incoming = copy.deepcopy(team)
    incoming.update(updated_at=clock(-10), last_attempt_at=clock(-10), last_error='old_failure')
    incoming['scopes']['10'].update(collected_at=clock(-5), maps={'Haven': {'w': 7}})
    assert db.install_prepared_snapshot(snapshot, {'1': incoming})['updated_teams'] == 1
    actual = db.get_analysis_teams()['1']
    assert actual['last_attempt_at'] == team['last_attempt_at']
    assert actual['last_error'] is None
    assert actual['scopes']['10'] == incoming['scopes']['10']
    assert db.install_prepared_snapshot(snapshot, {'1': incoming})['updated_teams'] == 0


def test_read_endpoints_keep_local_phase_after_an_older_feed_poll(client, monkeypatch):
    snapshot, _ = fixture_data()
    db.save_catalog_snapshot(snapshot)
    db.set_sync_status('error', {'source': 'github_hourly', 'catalog_generation': 'remote-old',
                               'collection': {'analysis': {'status': 'completed',
                                                          'catalog_generation': 'remote-old'}}})
    phase = {'status': 'partial', 'catalog_generation': 'local',
             'started_at': clock(-15), 'completed_at': clock(-1)}
    recovery._save_status({'status': 'partial', 'catalog_generation': 'local',
                          'collection': {'analysis': phase}, 'next_retry_at': clock(14)})
    forbidden = Mock(side_effect=AssertionError('HTTP reads must not start a collector'))
    monkeypatch.setattr(recovery, 'maybe_start', forbidden)
    response = client.get('/api/catalog').json()
    assert response['sync_status'] == 'degraded'
    assert response['sync_details']['catalog_generation'] == 'local'
    assert response['sync_details']['collection']['catalog'] == snapshot['collection']
    assert response['sync_details']['collection']['analysis'] == phase
    assert response['sync_details']['data_origin'] == 'render_recovery'
    assert client.get('/api/sync/status').json()['details']['collection']['analysis'] == phase
    forbidden.assert_not_called()


def test_local_phase_does_not_leak_into_newer_remote_generation():
    snapshot, _ = fixture_data()
    snapshot.update(generation='remote-new', updated_at=clock(), data_origin='github_hourly')
    snapshot['collection'].update(catalog_generation='remote-new')
    db.save_catalog_snapshot(snapshot)
    db.set_sync_status('completed', {'source': 'github_hourly', 'catalog_generation': 'remote-new'})
    recovery._save_status({'status': 'partial', 'collection': {'analysis': {
        'status': 'partial', 'catalog_generation': 'local', 'completed_at': clock(-1)}}})
    result = catalog.read_sync_status()
    assert result['status'] == 'completed'
    assert 'analysis' not in result['details']['collection']


def test_successful_analysis_only_recovery_clears_old_partial_status():
    snapshot, _ = fixture_data()
    snapshot.pop('data_origin')
    db.save_catalog_snapshot(snapshot)
    db.set_sync_status('degraded', {'source': 'github_hourly', 'catalog_generation': 'local',
                                  'collection': {'analysis': {
                                      'status': 'partial', 'catalog_generation': 'local',
                                      'completed_at': clock(-10)}}})
    recovery._save_status({'status': 'completed', 'collection': {'analysis': {
        'status': 'completed', 'catalog_generation': 'local', 'completed_at': clock(-1)}}})
    result = catalog.read_sync_status()
    assert result['status'] == 'completed'
    assert result['details']['external_sync_status'] == 'degraded'
    assert result['details']['collection']['analysis']['status'] == 'completed'
