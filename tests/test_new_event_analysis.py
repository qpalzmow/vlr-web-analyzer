from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from app import analysis, analysis_sources as sources, db


def current_team():
    stamp = analysis.now_iso()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp, 'last_success_at': stamp,
            'available_events': ['20'], 'scopes': {
                key: {'maps': {}, 'players': {}, 'collected_at': stamp, 'career_roster_verified': True}
                for key in ('all', '20')}}


def matches():
    return [{'selection_data': {'details': {'team_a_id': '1', 'team_b_id': '2'},
                               'team_a_events': [{'id': '20'}, {'id': '21'}],
                               'team_b_events': [{'id': '20'}]}}]


def install_old_overview(monkeypatch, available=('20', '21')):
    monkeypatch.setattr(sources, 'refresh_started_at', None)
    db.save_analysis_source('overview:1', {'maps': {}, 'available_events': ['20']})
    html = '<select name="event_id">' + ''.join(f'<option value="{i}">{i}</option>' for i in available) + '</select>'
    page = Mock(return_value=BeautifulSoup(html, 'html.parser'))
    monkeypatch.setattr(sources, 'page', page)
    monkeypatch.setattr(sources, 'parse_maps', lambda _: {})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {'name': 'Team', 'roster': {}, 'form': []})
    return page


def test_own_participation_helper_never_attributes_opponents_event_to_other_team():
    assert analysis.own_event_requirements(matches()) == {'1': {'20', '21'}, '2': {'20'}}
    assert analysis.requirements(matches()) == {'1': {'20', '21'}, '2': {'20', '21'}}


def test_new_own_event_refreshes_only_outdated_overview_and_prepares_missing_scope(monkeypatch):
    for tid in ('1', '2'):
        db.save_analysis_team(tid, current_team())
    page = install_old_overview(monkeypatch)
    maps = Mock(return_value={'Bind': {'played': 3, 'w': 2, 'l': 1}})
    monkeypatch.setattr(sources, 'event_maps', maps)
    result = analysis.refresh_analysis(matches())
    assert result == {'updated': 1, 'failed': 0, 'total': 1}
    page.assert_called_once_with('https://www.vlr.gg/team/stats/1')
    maps.assert_called_once_with('1', '21')
    records = db.get_analysis_teams()
    assert analysis.aggregate_team(records['1'], ['21'])['maps']['Bind']['played'] == 3
    assert analysis.aggregate_team(records['2'], ['21'])['maps'] == {}
    assert '21' not in records['2']['scopes']
    # The newly validated overview and scope are now reused normally.
    assert analysis.refresh_analysis(matches()) == {'updated': 0, 'failed': 0, 'total': 0}
    sources.team_overview('1', expected_events={'21'})
    assert page.call_count == 1


def test_failed_new_participation_fetch_is_pending_not_nonparticipant_zero(monkeypatch):
    original = current_team()
    for tid in ('1', '2'):
        db.save_analysis_team(tid, original)
    page = install_old_overview(monkeypatch)
    page.side_effect = RuntimeError('upstream unavailable')
    assert analysis.refresh_analysis(matches()) == {'updated': 0, 'failed': 1, 'total': 1}
    record = db.get_analysis_teams(['1'])['1']
    assert record['scopes'] == original['scopes']
    assert record['available_events'] == ['20', '21']
    assert record['last_error'] == 'team_collection_failed'
    with pytest.raises(analysis.AnalysisNotReady):
        analysis.aggregate_team(record, ['21'])


def test_catalog_confirmed_participation_survives_lagging_overview_and_scope_failure(monkeypatch):
    for tid in ('1', '2'):
        db.save_analysis_team(tid, current_team())
    install_old_overview(monkeypatch, available=('20',))
    maps = Mock(side_effect=RuntimeError('event statistics missing'))
    monkeypatch.setattr(sources, 'event_maps', maps)
    assert analysis.refresh_analysis(matches()) == {'updated': 0, 'failed': 1, 'total': 1}
    maps.assert_called_once_with('1', '21')
    record = db.get_analysis_teams(['1'])['1']
    assert record['failed_scopes'] == ['21']
    assert record['available_events'] == ['20', '21']
    with pytest.raises(analysis.AnalysisNotReady):
        analysis.aggregate_team(record, ['21'])


def test_new_participation_metadata_is_repaired_even_if_merge_kept_fresh_event_scope(monkeypatch):
    old = current_team()
    old['scopes']['21'] = dict(old['scopes']['20'])
    db.save_analysis_team('1', old)
    db.save_analysis_team('2', current_team())
    install_old_overview(monkeypatch)
    maps = Mock(side_effect=AssertionError('Fresh scope need not be collected twice'))
    monkeypatch.setattr(sources, 'event_maps', maps)
    assert analysis.refresh_analysis(matches()) == {'updated': 1, 'failed': 0, 'total': 1}
    assert db.get_analysis_teams(['1'])['1']['available_events'] == ['20', '21']
    maps.assert_not_called()
