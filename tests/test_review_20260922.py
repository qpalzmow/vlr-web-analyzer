import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import httpx
import pytest
from bs4 import BeautifulSoup
from app import analysis, analysis_sources as sources, catalog, db, main
from app.scraper import parsers, vlr
from app.scraper.metrics import simulate_banpick

FIXTURES = Path(__file__).parent / 'fixtures'


def record():
    stamp = datetime.now(timezone.utc).isoformat()
    p = {'name': 'Transferred player', 'rounds': 10000, 'weighted_acs': 2500000,
         'kills': 10000, 'deaths': 9000, 'fk': 2800, 'fd': 2447, 'agents': {'jett': 10000}}
    scope = {'collected_at': stamp, 'maps': {'Bind': {'played': 2, 'w': 1, 'l': 1,
             'atk_total': 15, 'def_total': 20}}, 'players': {'1': p},
             'players_available': True, 'career_roster_verified': True}
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp,
            'last_success_at': stamp, 'available_events': ['20'], 'failed_scopes': [],
            'scopes': {'all': scope, '20': copy.deepcopy(scope)}}


def test_career_intro_is_separate_from_team_metrics_and_event_membership():
    data = record()
    db.save_analysis_team('1', data)
    db.save_analysis_team('2', data)
    result = analysis.full_analysis('1', '2', None, [])
    assert result['ace_a']['acs'] == 250
    assert result['adv_a']['fk_fd_margin'] is None
    assert result['adv_a']['total_fk'] is None
    assert result['probability'] is None
    filtered = analysis.full_analysis('1', '2', ['20'], [])
    assert filtered['ace_a']['nickname'] == 'N/A'
    assert filtered['players_available'] is False
    assert filtered['probability'] is None


@pytest.mark.parametrize('players', [{}, {'1': {'rounds': 0}}, {'1': {'rounds': 5}, '2': {'rounds': 0}}])
def test_empty_or_incomplete_career_cannot_be_available(players):
    data = record()
    data['scopes']['all']['players'] = players
    result = analysis.aggregate_team(data)
    assert result['players_available'] is False
    assert result['ace']['nickname'] == 'N/A'


def test_team_refresh_failure_and_old_scopes_remain_stale(monkeypatch):
    prior = record()
    db.save_analysis_team('1', prior)
    matches = [{'selection_data': {'details': {'team_a_id': '1'}, 'team_a_events': [{'id': '20'}]}}]
    monkeypatch.setattr(sources, 'team_overview', Mock(side_effect=RuntimeError('403')))
    assert analysis.refresh_analysis(matches, force=True)['failed'] == 1
    failed = db.get_analysis_teams()['1']
    assert failed['scopes'] == prior['scopes']
    assert failed['last_success_at'] == prior['last_success_at']
    assert failed['last_attempt_at'] and failed['last_error']
    assert analysis.aggregate_team(failed)['stale']
    old = record()
    old['scopes']['all']['collected_at'] = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    assert analysis.aggregate_team(old)['stale']


def test_actual_match_status_fragment_and_stage_names():
    html = (FIXTURES/'match-final.html').read_text(encoding='utf-8')
    assert parsers.parse_live_score(html)['status'] == 'final'
    soup = BeautifulSoup(html, 'html.parser')
    soup.select_one('.match-header-event-series').string = 'Upper Semifinals'
    soup.select_one('.match-header-vs-note').string = 'LIVE'
    assert parsers.parse_live_score(str(soup))['status'] == 'live'
    soup.select_one('.match-header-event-series').string = 'Grand Final'
    soup.select_one('.match-header-vs-note').decompose()
    assert parsers.parse_live_score(str(soup))['status'] == 'upcoming'
    assert parsers.parse_live_score((FIXTURES/'match-upcoming.html').read_text(encoding='utf-8'))['status'] == 'upcoming'


def test_forbidden_match_does_not_become_tbd_or_remove_previous_selection(monkeypatch):
    request = httpx.Request('GET', 'https://www.vlr.gg/1')
    monkeypatch.setattr(vlr, 'request_with_retry', lambda _: httpx.Response(403, text='<html>Forbidden</html>', request=request))
    with pytest.raises(httpx.HTTPStatusError):
        vlr.get_match_details('https://www.vlr.gg/1')
    monkeypatch.setattr(vlr, 'request_with_retry', lambda _: httpx.Response(200, text='<html>Error</html>', request=request))
    with pytest.raises(ValueError):
        vlr.get_match_details('https://www.vlr.gg/1')
    previous = {'ready_count': 1, 'matches': [{'id': '1', 'selection_data': {'details': {'team_a_id': '1', 'team_b_id': '2'}}}]}
    monkeypatch.setattr(catalog, 'get_matches', lambda **kw: [{'id': '1', 'url': '/1'}, {'id': '2', 'url': '/2'}])
    def details(url):
        if url.endswith('/1'):
            raise httpx.HTTPStatusError('403', request=request, response=httpx.Response(403, request=request))
        return {'team_a_id': '3', 'team_b_id': '4'}
    monkeypatch.setattr(catalog, 'get_match_details', details)
    monkeypatch.setattr(catalog, 'get_team_events', lambda *a, **kw: [])
    result = catalog.build_snapshot(previous)
    assert result['ready_count'] == 2
    assert result['matches'][0]['selection_data']['stale'] is True


def test_parsing_corruption_cannot_overwrite_good_data(monkeypatch):
    malformed = BeautifulSoup('<table class="mod-team-maps"><tbody><tr><td>Bind (10)</td><td>5</td></tr></tbody></table>', 'html.parser')
    with pytest.raises(ValueError):
        sources.parse_maps(malformed)
    with pytest.raises(ValueError):
        sources.parse_player(BeautifulSoup('<div class="player-header"><h1>Player</h1></div>', 'html.parser'))
    maps = BeautifulSoup((FIXTURES/'maps.html').read_text(encoding='utf-8'), 'html.parser')
    assert 'Corrode' in sources.parse_maps(maps)
    maps.select_one('tbody td').string = 'FutureMap (4)'
    with pytest.raises(ValueError):
        sources.parse_maps(maps)
    assert sources.parse_player(BeautifulSoup((FIXTURES/'player.html').read_text(encoding='utf-8'), 'html.parser'))['rounds'] > 10000
    prior = record()
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': ['20']})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {'name': 'One', 'roster': {}, 'form': []})
    monkeypatch.setattr(sources, 'event_maps', lambda *a: sources.parse_maps(malformed))
    assert analysis.prepare_team('1', ['20'], prior)['scopes']['20'] == prior['scopes']['20']


@pytest.mark.parametrize(('value', 'expected'), [('1,234',1234),('-1,234',-1234),('',0),('1,23',0),('12 / 30',0),('1234.5',0),('Score: -45 pts',-45)])
def test_strict_integer_grouping(value, expected):
    assert parsers.safe_int(value) == expected


def test_body_limit_applies_to_streamed_bytes(client):
    body = json.dumps({'message': 'a'*20000}).encode()
    result = client.post('/api/log-error', content=(body[i:i+1000] for i in range(0,len(body),1000)))
    assert 'content-length' not in result.request.headers
    assert result.status_code == 413
    assert client.post('/api/log-error', json={'message': 'small'}).status_code == 200


@pytest.mark.parametrize('stats', ['bad', None, {'played': -1}, {'played': 1, 'w': 2}, {'played': 3, 'w': 1, 'l': 1}, {'played': True}, {'atk_won': 3, 'atk_total': 2}])
def test_invalid_map_stats_are_rejected(client, stats):
    assert client.post('/api/simulate/banpick', json={'maps_a': {'Bind': stats}, 'map_pool': ['Bind']}).status_code == 422


def test_recommendations_never_invent_decider_and_account_for_remaining_maps():
    pool = ['Bind','Ascent','Split','Haven','Lotus','Breeze','Abyss']
    result = simulate_banpick({}, {}, pool)
    assert result['mode'] == 'recommendations'
    assert all(p['team'] != 'Decider' for p in result['picks'])
    assert sorted([r['map'] for r in result['bans']+result['picks']] + result['remaining']) == sorted(pool)
    assert result == simulate_banpick({}, {}, list(reversed(pool)))


def test_legacy_analysis_routes_only_read_prepared_data(client, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('No external work'))
    monkeypatch.setattr(main._global_executor, 'submit', forbidden)
    db.save_analysis_team('1', record())
    for route in ('form', 'maps', 'aces', 'advanced'):
        assert client.post('/api/analyze/'+route, json={'team_a_id':'1'}).status_code == 200
        assert client.post('/api/analyze/'+route, json={'team_a_id':'999'}).status_code == 409
    forbidden.assert_not_called()


@pytest.mark.parametrize('port', [None, '8080'])
def test_container_entrypoint_respects_port(port):
    env = dict(os.environ)
    env.pop('PORT', None)
    if port: env['PORT'] = port
    code = "import runpy,uvicorn; uvicorn.run=lambda *a,**k: print(k['port']); runpy.run_module('app.entrypoint',run_name='__main__')"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, check=True)
    assert result.stdout.strip() == (port or '7860')


def test_analytics_keeps_latest_pending_generation(monkeypatch):
    entered, release, completed = Event(), Event(), Event()
    seen = []
    def refresh(matches, **kw):
        seen.append(matches)
        if len(seen) == 1:
            entered.set()
            assert release.wait(5)
        else:
            completed.set()
    monkeypatch.setattr(analysis, 'refresh_analysis', refresh)
    monkeypatch.setattr(catalog, '_stop', Event())
    monkeypatch.setattr(catalog, '_analytics_worker', None)
    monkeypatch.setattr(catalog, '_analytics_pending', None)
    catalog.queue_analytics(['old'])
    assert entered.wait(5)
    catalog.queue_analytics(['middle'])
    catalog.queue_analytics(['new'])
    release.set()
    assert completed.wait(5)
    worker = catalog._analytics_worker
    if worker: worker.join(5)
    assert seen == [['old'], ['new']]
