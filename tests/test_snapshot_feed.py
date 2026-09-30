import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app import catalog, db, snapshot_feed as feed
from app.snapshot_export import write_snapshot


def bundle():
    db.init_db()
    catalog.bootstrap_snapshot()
    from app.analysis import bootstrap_analysis
    bootstrap_analysis()
    return {'schema_version': 1, 'published_at': datetime.now(timezone.utc).isoformat(),
            'catalog': db.get_catalog_snapshot(),
            'analysis': {'schema_version': 3, 'teams': db.get_analysis_teams()}}


def test_render_uses_external_feed_and_local_run_keeps_local_scheduler(monkeypatch):
    assert not feed.enabled()
    monkeypatch.setenv('RENDER', 'true')
    assert feed.enabled()
    monkeypatch.setenv('VLR_REFRESH_MODE', 'local')
    assert not feed.enabled()


def test_import_updates_catalog_and_analysis_together_and_never_rolls_back():
    data = bundle()
    old = copy.deepcopy(data)
    fresh = datetime.now(timezone.utc).isoformat()
    tid = next(iter(data['analysis']['teams']))
    data['catalog'].update(updated_at=fresh, generation='new')
    data['analysis']['teams'][tid].update(updated_at=fresh, last_attempt_at=fresh, last_error=None)
    assert feed.install(data) == {'catalog_changed': True, 'updated_teams': 1}
    assert db.get_catalog_snapshot()['generation'] == 'new'
    assert db.get_analysis_teams([tid])[tid]['updated_at'] == fresh
    assert feed.install(old) == {'catalog_changed': False, 'updated_teams': 0}
    assert feed.install(data) == {'catalog_changed': False, 'updated_teams': 0}
    assert db.get_catalog_snapshot()['generation'] == 'new'


@pytest.mark.parametrize('break_data', [
    lambda p: p.update(schema_version=999),
    lambda p: p['catalog'].update(ready_count=999),
    lambda p: p['catalog'].update(matches=[]),
    lambda p: p['catalog'].update(updated_at='yesterday'),
    lambda p: p['analysis'].update(schema_version=999),
    lambda p: p['analysis'].update(teams={}),
    lambda p: p.update(published_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()),
])
def test_invalid_generation_cannot_replace_previous_data(break_data):
    data = bundle()
    prior = copy.deepcopy(db.get_catalog_snapshot())
    break_data(data)
    with pytest.raises((ValueError, KeyError, TypeError)):
        feed.install(data)
    assert db.get_catalog_snapshot() == prior


def test_remote_refresh_does_not_scrape_and_stale_timestamp_is_not_faked(monkeypatch):
    data = bundle()
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setattr(feed, 'download', lambda: data)
    forbidden = Mock(side_effect=AssertionError('Render must not rescrape'))
    monkeypatch.setattr(catalog, 'build_snapshot', forbidden)
    monkeypatch.setattr(catalog, 'queue_analytics', forbidden)
    result = catalog.refresh_catalog()
    assert result['status'] == 'degraded'
    assert result['details']['source'] == 'github_hourly'
    assert result['details']['last_error'] == 'snapshot_outdated'
    assert db.get_catalog_snapshot()['updated_at'] == data['catalog']['updated_at']
    forbidden.assert_not_called()


def test_missing_feed_preserves_last_generation_and_retries(monkeypatch):
    data = bundle()
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setattr(feed, 'download', Mock(side_effect=RuntimeError('offline')))
    result = catalog.refresh_catalog()
    assert result['status'] == 'error'
    assert result['details']['last_error'] == 'RuntimeError'
    assert db.get_catalog_snapshot() == data['catalog']
    assert datetime.fromisoformat(result['details']['next_refresh_at']) < datetime.now(timezone.utc)+timedelta(minutes=6)


def test_export_preserves_scope_dates_and_has_no_private_source_cache(tmp_path):
    data = bundle()
    path = tmp_path/'snapshot.json'
    exported = write_snapshot(path)
    assert exported['catalog'] == data['catalog']
    assert exported['analysis'] == data['analysis']
    assert set(exported) == {'schema_version', 'published_at', 'catalog', 'analysis'}
    assert path.exists() and not path.with_suffix('.tmp').exists()


def test_database_install_is_atomic_on_failure():
    data = bundle()
    prior = db.get_catalog_snapshot()
    data['catalog'].update(updated_at=datetime.now(timezone.utc).isoformat(), generation='broken')
    broken = {'999': {'schema_version': 3, 'updated_at': 'invalid'}}
    with pytest.raises(ValueError):
        db.install_prepared_snapshot(data['catalog'], broken)
    assert db.get_catalog_snapshot() == prior
    assert '999' not in db.get_analysis_teams()


def test_budgeted_analysis_prioritizes_old_teams_and_exports_progress(monkeypatch):
    from threading import Event
    from app import analysis
    stop = Event()
    previous = {str(i): {'updated_at': f'2026-09-{30-i:02d}T00:00:00+00:00'} for i in range(5)}
    monkeypatch.setattr(analysis, 'get_analysis_teams', lambda: previous)
    monkeypatch.setattr(analysis, 'requirements', lambda _: {str(i): set() for i in range(5)})
    prepare = Mock(return_value={})
    monkeypatch.setattr(analysis, 'prepare_team', prepare)
    progress = []
    def completed(result):
        progress.append(result)
        stop.set()
    result = analysis.refresh_analysis([], force=True, stop=stop, on_progress=completed)
    assert {call.args[0] for call in prepare.call_args_list} == {'1', '2', '3', '4'}
    assert result == {'updated': 4, 'failed': 0, 'total': 5}
    assert len(progress) == 4 and progress[-1]['updated'] == 4


def test_status_counts_current_catalog_teams_including_missing_ones():
    from app.analysis import analysis_status
    data = bundle()
    data['catalog']['matches'][0]['selection_data']['details'].update(team_a_id='888888', team_b_id='999999')
    db.save_catalog_snapshot({**data['catalog'], 'matches': data['catalog']['matches'][:1]})
    status = analysis_status()
    assert status['teams'] == 2
    assert status['pending_teams'] == 2
    assert status['stale_teams'] == 2
    assert status['stored_teams'] > 2
