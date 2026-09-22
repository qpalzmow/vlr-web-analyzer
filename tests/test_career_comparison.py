import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import analysis, analysis_sources as sources, db
from app.scraper.metrics import find_ace_player_from_stats


def player(name='Career', rounds=100, acs=240, kills=90, deaths=60):
    return {'name': name, 'rounds': rounds, 'weighted_acs': rounds * acs,
            'kills': kills, 'deaths': deaths, 'fk': 15, 'fd': 10,
            'agents': {'jett': rounds}}


def record():
    stamp = analysis.now_iso()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp,
            'available_events': ['20', '21'], 'failed_scopes': [],
            'scopes': {
                'all': {'collected_at': stamp, 'career_roster_verified': True,
                        'players_available': True, 'players': {'7': player()},
                        'maps': {'Bind': {'played': 100, 'w': 60, 'l': 40}}},
                # Legacy event player data must never leak into career selection.
                '20': {'collected_at': stamp, 'players': {'8': player('Event star', acs=400)},
                       'maps': {'Bind': {'played': 2, 'w': 1, 'l': 1}}},
                '21': {'collected_at': stamp, 'players': {},
                       'maps': {'Bind': {'played': 4, 'w': 3, 'l': 1}}}}}


@pytest.mark.parametrize('events,played', [(None, 100), ([], 100), (['20'], 2),
    (['21'], 4), (['20', '21', '20'], 6), (['999'], 0)])
def test_map_filters_never_change_career_or_invent_team_player_metrics(events, played):
    data = record()
    db.save_analysis_team('1', data)
    db.save_analysis_team('2', data)
    result = analysis.full_analysis('1', '2', events, ['Bind', 'Haven'])
    assert result['ace_a'] == analysis.career_comparison(data)
    assert result['ace_a']['nickname'] == 'Career'
    assert result['ace_a']['scope'] == 'career'
    assert result['players_available'] is True
    assert result['adv_a']['total_played'] == played
    assert result['adv_a']['total_fk'] is None
    assert result['adv_a']['fk_fd_per_round'] is None
    assert result['probability'] is None


def test_recordless_roster_member_is_disclosed_without_hiding_recorded_players():
    data = record()
    scope = data['scopes']['all']
    scope['players']['9'] = {**sources.empty_player(), 'name': 'Newcomer'}
    # Existing stored scopes used False for any zero-round roster member.
    scope['players_available'] = False
    ace = analysis.aggregate_team(data, ['20'])['ace']
    assert ace['available'] and ace['partial']
    assert ace['nickname'] == 'Career'
    assert ace['roster_size'] == 2 and ace['players_with_stats'] == 1
    assert ace['missing_players'] == ['Newcomer']
    assert ace['unavailable_reason'] is None


@pytest.mark.parametrize('case,reason', [('empty', 'no_roster'), ('zero', 'no_player_stats'),
    ('unverified', 'roster_unverified'), ('absent', 'career_not_ready')])
def test_unavailable_career_has_reason_and_no_synthetic_numbers(case, reason):
    data = record()
    scope = data['scopes']['all']
    if case == 'empty':
        scope['players'] = {}
    elif case == 'zero':
        scope['players'] = {'9': {**sources.empty_player(), 'name': 'Newcomer'}}
    elif case == 'unverified':
        scope.pop('career_roster_verified')
    else:
        del data['scopes']['all']
    result = analysis.aggregate_team(data, ['20'])
    ace = result['ace']
    assert result['maps']['Bind']['played'] == 2
    assert ace['available'] is False
    assert ace['unavailable_reason'] == reason
    for field in ['acs', 'kd_margin', 'kd_ratio', 'rounds', 'kills', 'deaths']:
        assert ace[field] is None


def test_filtered_report_accounts_for_old_or_failed_career_snapshot():
    data = record()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    data['scopes']['all']['collected_at'] = old
    result = analysis.aggregate_team(data, ['20'])
    assert result['stale'] is True
    assert result['updated_at'] == old
    assert result['ace']['collected_at'] == old
    data['scopes']['all']['collected_at'] = analysis.now_iso()
    data['failed_scopes'] = ['all']
    assert analysis.aggregate_team(data, ['20'])['stale'] is True


def test_failed_player_fetch_preserves_entire_verified_snapshot(monkeypatch):
    prior = record()
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': ['20']})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {
        'name': 'Team', 'form': [], 'roster': {'7': 'Career', '9': 'Newcomer'}})
    monkeypatch.setattr(sources, 'player_totals', Mock(side_effect=[player(), RuntimeError('403')]))
    monkeypatch.setattr(sources, 'event_maps', lambda *args: {})
    prepared = analysis.prepare_team('1', ['20'], prior)
    assert prepared['scopes']['all'] == prior['scopes']['all']
    assert prepared['failed_scopes'] == ['all']
    result = analysis.aggregate_team(prepared, ['20'])
    assert result['stale'] is True
    assert result['ace']['partial'] is False  # Fetch failures are not recordless players.


def test_refresh_publishes_explicit_zero_round_member_with_coverage(monkeypatch):
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': []})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {
        'name': 'Team', 'form': [], 'roster': {'7': 'Career', '9': 'Newcomer'}})
    monkeypatch.setattr(sources, 'player_totals', lambda pid: player() if pid == '7' else sources.empty_player())
    prepared = analysis.prepare_team('1', [])
    assert prepared['scopes']['all']['players_available'] is True
    assert not prepared['failed_scopes']
    assert analysis.career_comparison(prepared)['missing_players'] == ['Newcomer']


def test_selection_uses_unrounded_acs_and_returns_actual_sample_and_ratio():
    lower = player('Lower', acs=238.81)
    higher = player('Higher', acs=238.84)
    higher['player_id'] = '7'
    ace = find_ace_player_from_stats([lower, higher])
    assert ace['nickname'] == 'Higher'
    assert ace['acs'] == 238.8
    assert ace['player_id'] == '7'
    assert ace['rounds'] == 100
    assert ace['kills'] == 90 and ace['deaths'] == 60
    assert ace['kd_ratio'] == 1.5 and ace['kd_margin'] == 30
    higher['deaths'] = 0
    assert find_ace_player_from_stats([higher])['kd_ratio'] is None


def test_equal_acs_prefers_larger_sample_independent_of_roster_order():
    short = player('Short', rounds=10)
    long = player('Long', rounds=100)
    assert find_ace_player_from_stats([short, long])['nickname'] == 'Long'
    assert find_ace_player_from_stats([long, short])['nickname'] == 'Long'


def test_all_analysis_apis_expose_same_career_without_scraping(client, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('Career must be precomputed'))
    monkeypatch.setattr(sources, 'page', forbidden)
    db.save_analysis_team('1', record())
    db.save_analysis_team('2', record())
    payload = {'team_a_id': '1', 'team_b_id': '2', 'event_ids': ['20']}
    full = client.post('/api/analyze', json=payload)
    aces = client.post('/api/analyze/aces', json=payload)
    assert full.status_code == aces.status_code == 200
    assert full.json()['ace_a'] == aces.json()['ace_a']
    assert full.json()['ace_a']['rounds'] == 100
    assert full.json()['ace_a']['available'] is True
    forbidden.assert_not_called()


def test_existing_seed_is_usable_without_refresh_and_newcomer_does_not_hide_ns():
    seed = json.loads((Path(__file__).resolve().parents[1] / 'data/analysis_seed.json').read_text(encoding='utf-8'))
    for tid in ['474', '624', '11060']:
        data = seed['teams'][tid]
        before = copy.deepcopy(data)
        career = analysis.aggregate_team(data)['ace']
        assert career['available'] is True
        prepared_events = [key for key in data['scopes'] if key != 'all']
        assert career == analysis.aggregate_team(data, prepared_events[:1])['ace']
        assert data == before
    ns = analysis.career_comparison(seed['teams']['11060'])
    assert ns['partial'] is True
    assert 'WoohyuN' in ns['missing_players']
