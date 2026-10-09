import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, call

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


@pytest.mark.parametrize('catalog_only', [True, False])
def test_catalog_only_export_preserves_analysis_and_default_still_refreshes(monkeypatch, tmp_path, catalog_only):
    import json
    import sys
    from app import snapshot_export as export
    data = bundle()
    path = tmp_path / 'snapshot.json'
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--output', str(path)] + (['--catalog-only'] if catalog_only else []))
    monkeypatch.setattr(export, 'bootstrap_snapshot', lambda: None)
    monkeypatch.setattr(export, 'bootstrap_analysis', lambda: None)
    monkeypatch.setattr(export, 'build_snapshot', lambda _: data['catalog'])
    refresh = Mock(return_value={'updated': 1})
    monkeypatch.setattr(export, 'refresh_analysis', refresh)
    export.main()
    assert json.loads(path.read_text(encoding='utf-8'))['analysis'] == data['analysis']
    if catalog_only:
        refresh.assert_not_called()
    else:
        refresh.assert_called_once()
        assert refresh.call_args.kwargs['force'] is False
        assert refresh.call_args.kwargs['stop'] is not None


def test_export_checkpoints_are_throttled_and_failure_can_retry(monkeypatch, tmp_path):
    from app import snapshot_export as export
    clock = [0]
    monkeypatch.setattr(export.time, 'monotonic', lambda: clock[0])
    writer = Mock()
    monkeypatch.setattr(export, 'write_snapshot', writer)
    checkpoint = export.SnapshotCheckpoint(tmp_path/'snapshot.json')
    for stamp in (0, 1, 59, 60, 61, 119, 120):
        clock[0] = stamp
        checkpoint({})
    assert writer.call_count == 2
    clock[0] = 180
    writer.side_effect = RuntimeError('disk failure')
    with pytest.raises(RuntimeError):
        checkpoint({})
    writer.side_effect = None
    checkpoint({})
    assert checkpoint.last_written == 180


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


@pytest.mark.parametrize('age, expected', [(3599, False), (3600, True), (7200, True)])
def test_collection_due_uses_catalog_clock_instead_of_checkpoint_publication(tmp_path, age, expected):
    import json
    from app.snapshot_export import collection_due
    data = bundle()
    now = datetime.now(timezone.utc)
    data['catalog']['updated_at'] = (now - timedelta(seconds=age)).isoformat()
    # A recent partial-analysis checkpoint must not postpone the next catalog update.
    data['published_at'] = now.isoformat()
    path = tmp_path / 'previous.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    assert collection_due(path, now=now) is expected


@pytest.mark.parametrize('previous_text', [None, 'invalid JSON', '{"schema_version":999}'])
def test_due_check_recovers_missing_or_invalid_snapshot_without_db_or_network(monkeypatch, tmp_path, capsys, previous_text):
    import sys
    from app import snapshot_export as export
    path = tmp_path / 'previous.json'
    if previous_text is not None:
        path.write_text(previous_text, encoding='utf-8')
    forbidden = Mock(side_effect=AssertionError('Due check must only read the published file'))
    for name in ('init_db', 'bootstrap_snapshot', 'bootstrap_analysis', 'build_snapshot', 'refresh_analysis'):
        monkeypatch.setattr(export, name, forbidden)
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--check-due', '--previous', str(path)])
    export.main()
    assert capsys.readouterr().out == 'true\n'
    forbidden.assert_not_called()


def test_due_check_prints_false_for_valid_recent_generation_without_output(monkeypatch, tmp_path, capsys):
    import json
    import sys
    from app import snapshot_export as export
    data = bundle()
    data['catalog']['updated_at'] = datetime.now(timezone.utc).isoformat()
    path = tmp_path / 'previous.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--check-due', '--previous', str(path)])
    forbidden = Mock(side_effect=AssertionError('Due check must not initialize storage'))
    monkeypatch.setattr(export, 'init_db', forbidden)
    export.main()
    assert capsys.readouterr().out == 'false\n'
    forbidden.assert_not_called()


def test_analysis_resume_restores_archived_teams_and_old_scopes_without_catalog_scrape(monkeypatch, tmp_path):
    import json
    import sys
    from app import snapshot_export as export
    data = bundle()
    archived = copy.deepcopy(next(iter(data['analysis']['teams'].values())))
    archived['team_id'] = '999999999'
    data['analysis']['teams']['999999999'] = archived
    previous = tmp_path / 'published.json'
    previous.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'new_runner.db'))
    monkeypatch.setattr(export, 'bootstrap_snapshot', lambda: None)
    monkeypatch.setattr(export, 'bootstrap_analysis', lambda: None)
    forbidden = Mock(side_effect=AssertionError('Analysis resume must keep the durable catalog'))
    monkeypatch.setattr(export, 'build_snapshot', forbidden)
    refreshed_tid = next(iter(data['analysis']['teams']))
    def refresh(matches, **kwargs):
        assert matches == data['catalog']['matches']
        assert kwargs['force'] is False
        team = db.get_analysis_teams([refreshed_tid])[refreshed_tid]
        team.update(last_attempt_at=datetime.now(timezone.utc).isoformat(), last_error='scope_collection_failed')
        db.save_analysis_team(refreshed_tid, team)
        return {'updated': 1, 'failed': 0, 'total': 1}
    monkeypatch.setattr(export, 'refresh_analysis', refresh)
    output = tmp_path / 'resumed.json'
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--analysis-only', '--previous', str(previous), '--output', str(output)])
    export.main()
    restored = json.loads(output.read_text(encoding='utf-8'))
    assert restored['catalog'] == data['catalog']
    assert restored['analysis']['teams']['999999999'] == archived
    assert restored['analysis']['teams'][refreshed_tid]['scopes'] == data['analysis']['teams'][refreshed_tid]['scopes']
    assert restored['collection']['mode'] == 'analysis_only'
    assert restored['collection']['status'] == 'partial'
    forbidden.assert_not_called()


def test_budget_expiry_publishes_finished_work_and_cleans_deadline(monkeypatch, tmp_path):
    import json
    import sys
    from app import snapshot_export as export
    from app.scraper import http
    data = bundle()
    monkeypatch.setattr(export, 'bootstrap_snapshot', lambda: None)
    monkeypatch.setattr(export, 'bootstrap_analysis', lambda: None)
    deadline = Mock()
    monkeypatch.setattr(http, 'set_collection_deadline', deadline)
    tid = next(iter(data['analysis']['teams']))
    fresh = datetime.now(timezone.utc).isoformat()
    def refresh(_matches, *, force, stop, on_progress):
        assert force is False
        team = db.get_analysis_teams([tid])[tid]
        team.update(updated_at=fresh, last_attempt_at=fresh)
        db.save_analysis_team(tid, team)
        results = {'updated': 1, 'failed': 0, 'total': 2}
        on_progress(results)
        stop.set()
        return results
    monkeypatch.setattr(export, 'refresh_analysis', refresh)
    output = tmp_path / 'checkpoint.json'
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--analysis-only', '--max-seconds', '1', '--output', str(output)])
    export.main()
    checkpoint = feed.validate(json.loads(output.read_text(encoding='utf-8')))
    assert checkpoint['analysis']['teams'][tid]['updated_at'] == fresh
    assert checkpoint['catalog'] == data['catalog']
    assert checkpoint['collection']['status'] == 'partial'
    assert checkpoint['collection']['budget_exhausted'] is True
    assert checkpoint['collection']['remaining_teams'] == 1
    assert checkpoint['collection']['completed_at']
    assert deadline.call_args_list == [call(1.0), call(None)]


def test_unexpected_analysis_error_still_writes_recoverable_final_checkpoint(monkeypatch, tmp_path):
    import json
    import sys
    from app import snapshot_export as export
    from app.scraper import http
    data = bundle()
    monkeypatch.setattr(export, 'bootstrap_snapshot', lambda: None)
    monkeypatch.setattr(export, 'bootstrap_analysis', lambda: None)
    deadline = Mock()
    monkeypatch.setattr(http, 'set_collection_deadline', deadline)
    def fail(_matches, **kwargs):
        kwargs['on_progress']({'updated': 1, 'failed': 0, 'total': 2})
        raise RuntimeError('collector failure')
    monkeypatch.setattr(export, 'refresh_analysis', fail)
    output = tmp_path / 'checkpoint.json'
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--analysis-only', '--output', str(output)])
    with pytest.raises(RuntimeError, match='collector failure'):
        export.main()
    checkpoint = feed.validate(json.loads(output.read_text(encoding='utf-8')))
    assert checkpoint['catalog'] == data['catalog']
    assert checkpoint['analysis'] == data['analysis']
    assert checkpoint['collection']['status'] == 'partial'
    assert checkpoint['collection']['results']['updated'] == 1
    assert checkpoint['collection']['error'] == 'RuntimeError'
    deadline.assert_called_with(None)


def test_render_cold_start_imports_durable_generation_into_empty_sqlite_before_serving(monkeypatch, tmp_path, client):
    from threading import Event
    data = bundle()
    data['catalog'].update(updated_at=datetime.now(timezone.utc).isoformat(), generation='durable-cold-start')
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'empty_render.db'))
    db.init_db()
    assert db.get_catalog_snapshot() is None
    assert db.get_analysis_teams() == {}
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setattr(feed, 'download', lambda: data)
    monkeypatch.setattr(catalog, 'bootstrap_snapshot', lambda: None)
    monkeypatch.setattr(catalog, '_worker', None)
    monkeypatch.setattr(catalog, '_stop', Event())
    class IdleThread:
        def __init__(self, **kwargs):
            self.name = kwargs['name']
        def start(self):
            if self.name == 'VLRHourlyCatalog':
                assert db.get_catalog_snapshot()['generation'] == 'durable-cold-start'
        def is_alive(self):
            return False
        def join(self, timeout=None):
            pass
    monkeypatch.setattr(catalog.threading, 'Thread', IdleThread)
    forbidden = Mock(side_effect=AssertionError('Render must import instead of scraping'))
    monkeypatch.setattr(catalog, 'build_snapshot', forbidden)
    monkeypatch.setattr(catalog, 'queue_analytics', forbidden)
    catalog.start_catalog_scheduler()
    assert client.get('/api/catalog').json()['generation'] == 'durable-cold-start'
    assert db.get_analysis_teams() == data['analysis']['teams']
    assert db.get_sync_status()['details']['source'] == 'github_hourly'
    forbidden.assert_not_called()
