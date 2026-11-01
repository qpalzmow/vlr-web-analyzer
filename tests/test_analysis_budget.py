import copy
from datetime import datetime, timedelta, timezone
from threading import Event, Lock

import pytest

from app import analysis, db
from app.scraper.http import CollectionBudgetExceeded


def previous_team():
    now = datetime.now(timezone.utc)
    fresh = now.isoformat()
    old = (now - timedelta(hours=2)).isoformat()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': old,
            'last_success_at': old, 'available_events': ['20', '21', '22'],
            'failed_scopes': [], 'scopes': {
                'all': {'maps': {}, 'players': {'7': {'rounds': 10}},
                        'career_roster_verified': True, 'collected_at': fresh},
                **{event: {'maps': {'Haven': {'played': 1}}, 'players': {}, 'collected_at': old}
                   for event in ('20', '21', '22')}}}


def install_team_sources(monkeypatch):
    monkeypatch.setattr(analysis.sources, 'team_overview', lambda _: {
        'maps': {}, 'available_events': ['20', '21', '22']})
    monkeypatch.setattr(analysis.sources, 'team_profile', lambda _: {
        'name': 'One', 'roster': {'7': 'Player'}, 'form': []})
    monkeypatch.setattr(analysis.sources, 'player_totals', lambda _: pytest.fail('Reuse the fresh verified career scope'))


def test_scope_budget_preserves_completed_and_previous_scopes_then_success_clears_state(monkeypatch):
    install_team_sources(monkeypatch)
    prior = previous_team()
    calls = []
    def maps(team_id, event_id):
        calls.append(event_id)
        if event_id == '21':
            raise CollectionBudgetExceeded('shared cooldown exceeds remaining time')
        return {'Lotus': {'played': 2}}
    monkeypatch.setattr(analysis.sources, 'event_maps', maps)
    prepared = analysis.prepare_team('1', ['20', '21', '22'], prior)
    assert calls == ['20', '21']
    assert prepared['budget_exhausted'] is True
    assert prepared['failed_scopes'] == ['21', '22']
    assert prepared['last_success_at'] == prior['last_success_at']
    assert prepared['scopes']['all'] == prior['scopes']['all']
    assert prepared['scopes']['20']['maps'] == {'Lotus': {'played': 2}}
    for event in ('21', '22'):
        assert prepared['scopes'][event] == prior['scopes'][event]
    assert db.get_analysis_teams(['1'])['1']['budget_exhausted'] is True

    monkeypatch.setattr(analysis.sources, 'event_maps', lambda *_: {})
    recovered = analysis.prepare_team('1', ['20', '21', '22'], prepared)
    assert recovered['budget_exhausted'] is False
    assert recovered['failed_scopes'] == []
    assert recovered['last_error'] is None
    assert recovered['scopes']['20'] == prepared['scopes']['20']
    assert db.get_analysis_teams(['1'])['1']['budget_exhausted'] is False


def test_career_budget_retains_whole_career_and_stops_event_requests(monkeypatch):
    install_team_sources(monkeypatch)
    prior = previous_team()
    prior['scopes']['all']['collected_at'] = prior['updated_at']
    def player(_):
        raise CollectionBudgetExceeded('no source budget')
    monkeypatch.setattr(analysis.sources, 'player_totals', player)
    monkeypatch.setattr(analysis.sources, 'event_maps', lambda *_: pytest.fail('No scope requests after budget expiry'))
    prepared = analysis.prepare_team('1', ['20', '21', '22'], prior)
    assert prepared['scopes'] == prior['scopes']
    assert prepared['budget_exhausted'] is True
    assert prepared['failed_scopes'] == ['all', '20', '21', '22']


def test_refresh_propagates_early_budget_before_timer_stop_and_does_not_count_success(monkeypatch):
    install_team_sources(monkeypatch)
    prior = previous_team()
    db.save_analysis_team('1', prior)
    monkeypatch.setattr(analysis, 'requirements', lambda _: {'1': {'20', '21', '22'}})
    def maps(*_):
        raise CollectionBudgetExceeded('429 cooldown does not fit remaining budget')
    monkeypatch.setattr(analysis.sources, 'event_maps', maps)
    stop = Event()
    progress = []
    result = analysis.refresh_analysis([], stop=stop, on_progress=progress.append)
    assert result == {'updated': 0, 'failed': 1, 'total': 1, 'budget_exhausted': True}
    assert stop.is_set()
    assert progress[-1] == result
    assert db.get_analysis_teams(['1'])['1']['scopes'] == prior['scopes']


@pytest.mark.parametrize('with_stop', [False, True])
def test_typed_team_failure_keeps_old_scopes_and_starts_no_second_batch(monkeypatch, with_stop):
    prior = previous_team()
    for team_id in range(1, 7):
        db.save_analysis_team(str(team_id), copy.deepcopy(prior))
    monkeypatch.setattr(analysis, 'requirements', lambda _: {str(i): {'20'} for i in range(1, 7)})
    calls, lock = [], Lock()
    def overview(team_id):
        with lock:
            calls.append(team_id)
        raise CollectionBudgetExceeded('deadline reached before team overview')
    monkeypatch.setattr(analysis.sources, 'team_overview', overview)
    stop = Event() if with_stop else None
    result = analysis.refresh_analysis([], stop=stop)
    assert result == {'updated': 0, 'failed': 4, 'total': 6, 'budget_exhausted': True}
    assert set(calls) == {'1', '2', '3', '4'}
    assert not with_stop or stop.is_set()
    stored = db.get_analysis_teams()
    assert stored['1']['scopes'] == prior['scopes']
    assert stored['1']['budget_exhausted'] is True
    assert stored['5'] == prior


def test_nonbudget_failures_keep_normal_three_key_result_shape(monkeypatch):
    prior = previous_team()
    prior['budget_exhausted'] = True
    db.save_analysis_team('1', prior)
    monkeypatch.setattr(analysis, 'requirements', lambda _: {'1': {'20'}})
    def offline(_):
        raise ValueError('Team page structure missing')
    monkeypatch.setattr(analysis.sources, 'team_overview', offline)
    stop = Event()
    assert analysis.refresh_analysis([], stop=stop) == {'updated': 0, 'failed': 1, 'total': 1}
    assert not stop.is_set()
    assert db.get_analysis_teams(['1'])['1']['budget_exhausted'] is False
