from datetime import datetime, timezone

import pytest

from app import db
from app.analysis import analysis_status


def test_initialization_preserves_existing_legacy_data():
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute('CREATE TABLE team_data (team_id TEXT, payload TEXT)')
            conn.execute("INSERT INTO team_data VALUES ('old', 'preserve')")
        db.init_db()
        assert conn.execute('SELECT payload FROM team_data').fetchone()[0] == 'preserve'
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    finally:
        conn.close()


def test_catalog_and_analysis_roundtrip():
    catalog = {'matches': [{'team_a': 'DRX', 'team_b': 'PRX'}]}
    team = {'scopes': {'all': {'players': {'1': {'acs': 260.0}}}}}
    db.save_catalog_snapshot(catalog)
    db.save_analysis_team('100', team)
    assert db.get_catalog_snapshot() == catalog
    assert db.get_analysis_teams(['100']) == {'100': team}
    assert db.get_analysis_teams([]) == {}


def test_seed_is_atomic_and_does_not_overwrite_collected_teams():
    collected = {'updated_at': 'new', 'scopes': {'all': {}}}
    db.save_analysis_team('100', collected)
    db.save_analysis_seed({'100': {'updated_at': 'old'}, '200': {'scopes': {}}})
    db.save_analysis_seed({'200': {'updated_at': 'overwrite'}})
    assert db.get_analysis_teams() == {'100': collected, '200': {'scopes': {}}}
    with pytest.raises(TypeError):
        db.save_analysis_seed({'300': {}, '400': {'invalid': object()}})
    assert '300' not in db.get_analysis_teams()


def test_metadata_distinguishes_explicit_failed_success_and_missing_timestamp():
    now = datetime.now(timezone.utc).isoformat()
    db.save_analysis_team('100', {'updated_at': now, 'scopes': {'all': {}}})
    db.save_analysis_team('200', {'updated_at': now, 'last_success_at': None,
                                 'last_error': 'failed', 'scopes': {}})
    db.save_analysis_team('300', {'updated_at': now})
    metadata, count = db.get_analysis_metadata(['100', '200', 'missing'])
    assert count == 3 and set(metadata) == {'100', '200'}
    assert metadata['100']['last_success_at'] == now
    assert metadata['200']['last_success_at'] is None
    assert analysis_status([]) == {'teams': 3, 'stored_teams': 3, 'failed_teams': 1,
                                   'pending_teams': 2, 'stale_teams': 1}
    assert db.get_analysis_metadata([]) == ({}, 3)


def test_status_never_loads_full_player_payloads(monkeypatch):
    from app import analysis
    db.save_analysis_team('100', {'scopes': {'all': {}}})
    def forbidden(*args):
        raise AssertionError('Status must only read metadata')
    monkeypatch.setattr(analysis, 'get_analysis_teams', forbidden)
    monkeypatch.setattr(analysis, 'get_catalog_snapshot', forbidden)
    assert analysis.analysis_status([])['teams'] == 1


def test_sync_status_counts_prepared_teams(client):
    db.save_analysis_team('100', {'scopes': {'all': {}}})
    db.set_sync_status('completed', {'synced': 1})
    assert db.get_sync_status()['synced_teams_count'] == 1
    assert db.get_sync_status()['details']['synced'] == 1
    response = client.get('/api/sync/status')
    assert response.status_code == 200
    assert response.json()['synced_teams_count'] == 1
