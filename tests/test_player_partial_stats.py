from unittest.mock import Mock

import httpx
import pytest
from bs4 import BeautifulSoup

from app import analysis, analysis_sources as sources, db
from app.scraper.metrics import find_ace_player_from_stats


def player_page(rows):
    headers = ['Agent', 'Use', 'Rnd', 'R', 'ACS', 'K:D', 'KAST', 'ADR',
               'KPR', 'APR', 'FK:FD', 'K', 'D', 'A', 'FK', 'FD']
    body = ''
    for index, (rounds, acs, kills, deaths) in enumerate(rows):
        cells = [f'<img alt="Agent{index}">', '100%', rounds, 1, acs, 1, 70,
                 100, 1, 1, 1, kills, deaths, 0, min(1, rounds), min(1, rounds)]
        body += '<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>'
    return BeautifulSoup('<table class="mod-agent-rows"><thead><tr>'
        + ''.join(f'<th>{h}</th>' for h in headers)
        + '</tr></thead><tbody>' + body + '</tbody></table>', 'html.parser')


def parsed_player(acs=250, name='Known'):
    return {**sources.parse_player(player_page([(100, acs, 90, 60)])), 'name': name}


def record(players):
    stamp = analysis.now_iso()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp,
            'last_success_at': stamp, 'available_events': ['20'], 'failed_scopes': [],
            'scopes': {'all': {'collected_at': stamp, 'career_roster_verified': True,
                              'players': players, 'maps': {}},
                       '20': {'collected_at': stamp, 'maps': {}}}}


def stub_team(monkeypatch, roster):
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': ['20']})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {'name': 'XLG', 'roster': roster, 'form': []})
    monkeypatch.setattr(sources, 'event_maps', lambda *args: {})


def test_blank_acs_keeps_counts_and_agents_but_never_invents_whole_career_average():
    # Sharks and SereNa both have a 21-round agent row with an empty ACS cell
    # in the VLR source checked 2026-11-02. Other rows must not hide that gap.
    player = {**sources.parse_player(player_page([(100, 250, 90, 60), (21, '', 18, 16)])),
              'name': 'Sharks'}
    assert player['rounds'] == 121 and player['kills'] == 108 and player['deaths'] == 76
    assert sum(player['agents'].values()) == 121
    assert player['weighted_acs'] is None and player['acs_available'] is False
    assert player['acs_missing_rounds'] == 21
    data = record({'64849': player})
    row = analysis.career_roster(data)[0]
    assert row['available'] is True and row['acs'] is None
    assert row['rounds'] == 121 and row['kd_ratio'] == round(108 / 76, 4)
    assert row['acs_unavailable_reason'] == 'source_acs_missing'
    ace = analysis.career_comparison(data)
    assert ace['available'] is False and ace['nickname'] == 'N/A'
    assert ace['players_with_stats'] == 1 and ace['players_with_acs'] == 0
    assert ace['players_missing_acs'] == ['Sharks'] and ace['partial'] is True
    assert ace['unavailable_reason'] == 'source_acs_missing'


@pytest.mark.parametrize('blank', ['', '-', '\u2014'])
def test_positive_round_acs_gap_invalidates_average_without_reducing_denominator(blank):
    player = sources.parse_player(player_page([(100, 300, 100, 80), (20, blank, 10, 10)]))
    assert player['rounds'] == 120 and player['kills'] == 110
    assert player['weighted_acs'] is None and player['acs_missing_rounds'] == 20
    assert find_ace_player_from_stats([player])['acs'] is None


def test_zero_round_blank_does_not_invalidate_recorded_acs_and_numeric_zero_is_real():
    player = sources.parse_player(player_page([(100, 0, 10, 10), (0, '', 0, 0)]))
    assert player['acs_available'] is True and player['acs_missing_rounds'] == 0
    assert find_ace_player_from_stats([player])['acs'] == 0


@pytest.mark.parametrize('bad', ['NaN', 'inf', 'Infinity', '-1', '250oops', '1.2.3',
                               'N/A', 'null', '1e999', '2_50'])
def test_malformed_acs_remains_collection_error_instead_of_missing(bad):
    with pytest.raises(ValueError, match='ACS'):
        sources.parse_player(player_page([(100, bad, 90, 60)]))


def test_acs_leader_and_coverage_preserve_players_with_only_counts():
    data = record({'1': parsed_player('', 'Sharks'), '2': parsed_player(230, 'Other'),
                   '3': {**sources.empty_player(), 'name': 'Newcomer'}})
    ace = analysis.career_comparison(data)
    assert ace['nickname'] == 'Other' and ace['acs'] == 230 and ace['available']
    assert ace['players_with_stats'] == 2 and ace['players_with_acs'] == 1
    assert ace['players_missing_acs'] == ['Sharks'] and ace['missing_players'] == ['Newcomer']
    assert ace['partial'] is True and ace['unavailable_reason'] is None
    assert len(analysis.career_roster(data)) == 3


def test_explicit_missing_acs_no_longer_freezes_entire_team_refresh(monkeypatch):
    stub_team(monkeypatch, {'1': 'Sharks', '2': 'Other'})
    monkeypatch.setattr(sources, 'player_totals', lambda pid: parsed_player('' if pid == '1' else 230))
    prepared = analysis.prepare_team('1', ['20'])
    assert prepared['last_error'] is None and prepared['failed_scopes'] == []
    scope = prepared['scopes']['all']
    assert scope['acs_missing_players'] == 1 and scope['acs_missing_rounds'] == 100
    assert analysis.career_comparison(prepared)['nickname'] == 'Other'


@pytest.mark.parametrize('failure', ['malformed', 'http'])
def test_real_parse_or_http_failure_still_preserves_prior_verified_scope(monkeypatch, failure):
    prior = record({'1': parsed_player()})
    stub_team(monkeypatch, {'1': 'Known'})
    if failure == 'malformed':
        fetch = lambda _: sources.parse_player(player_page([(100, 'NaN', 90, 60)]))
    else:
        request = httpx.Request('GET', 'https://www.vlr.gg/player/1/')
        fetch = Mock(side_effect=httpx.HTTPStatusError('403', request=request,
                                                     response=httpx.Response(403, request=request)))
    monkeypatch.setattr(sources, 'player_totals', fetch)
    prepared = analysis.prepare_team('1', ['20'], prior, force=True)
    assert prepared['scopes']['all'] == prior['scopes']['all']
    assert prepared['failed_scopes'] == ['all']
    assert prepared['last_error'] == 'scope_collection_failed'


def test_cached_legacy_numeric_records_remain_usable_without_migration():
    legacy = parsed_player(230)
    for key in ['acs_available', 'acs_unavailable_reason', 'acs_missing_rounds']:
        legacy.pop(key)
    assert analysis.career_comparison(record({'1': legacy}))['acs'] == 230


def test_api_returns_known_counts_with_null_acs_without_upstream_request(client, monkeypatch):
    db.save_analysis_team('1', record({'1': parsed_player('', 'Sharks')}))
    db.save_analysis_team('2', record({'2': parsed_player(230, 'Known')}))
    monkeypatch.setattr(sources, 'page', Mock(side_effect=AssertionError('No request-time scrape')))
    response = client.post('/api/analyze', json={'team_a_id': '1', 'team_b_id': '2', 'event_ids': None, 'map_pool': []})
    assert response.status_code == 200
    result = response.json()
    assert result['ace_a']['available'] is False and result['ace_b']['acs'] == 230
    assert result['roster_a'][0]['acs'] is None and result['roster_a'][0]['kd_ratio'] == 1.5
    assert result['stale'] is False
