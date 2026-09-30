from pathlib import Path
from unittest.mock import Mock
from bs4 import BeautifulSoup
import pytest

from app import analysis, analysis_sources as sources, db, logos
from app.scraper.parsers import parse_match_details, parse_scheduled_time

FIXTURES = Path(__file__).parent / 'fixtures'


def player(name='Career', acs=240):
    return {'name': name, 'rounds': 100, 'weighted_acs': 100 * acs, 'kills': 90, 'deaths': 60, 'agents': {'jett':100}}


def record():
    stamp = analysis.now_iso()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp, 'available_events':['20'],
            'scopes': {'all': {'maps':{}, 'players':{'7':player()}, 'career_roster_verified':True, 'collected_at':stamp},
                       '20': {'maps':{}, 'players':{}, 'collected_at':stamp}}}


def test_real_match_context_uses_labelled_timezone_not_legacy_utc_attribute():
    html = (FIXTURES / 'match-context.html').read_text(encoding='utf-8')
    details = parse_match_details(html, 'https://www.vlr.gg/753451')
    assert details['scheduled_at'] == '2026-09-30T09:00:00+00:00'
    assert details['schedule_source_zone'] == 'KST'
    assert details['team_a_id'] == '2059' and details['team_b_id'] == '6961'
    assert details['match_format'] == 'BO3'
    assert details['live_score']['status'] == 'final'
    assert details['live_score']['series_score_a'] == '2'
    assert details['team_a_logo'] == 'https://owcdn.net/img/6466d79e1ed40.png'
    assert details['actual_veto'][0] == {'team': 'VIT', 'action': 'ban', 'map': 'Sunset'}
    assert details['actual_veto'][-1] == {'team': None, 'action': 'remaining', 'map': 'Lotus'}
    assert len(details['actual_veto']) == 7


@pytest.mark.parametrize('day,raw,clock,expected', [
    ('Wednesday, September 30', '2026-09-30 05:00:00', '5:00 AM EDT', '2026-09-30T09:00:00+00:00'),
    ('Wednesday, September 30', '2026-09-30 05:00:00', '11:00 AM CEST', '2026-09-30T09:00:00+00:00'),
    ('Thursday, January 1', '2025-12-31 14:00:00', '4:00 AM KST', '2025-12-31T19:00:00+00:00'),
    ('Thursday, January 1', '2026-01-01 05:00:00', '5:00 AM EST', '2026-01-01T10:00:00+00:00'),
    ('Wednesday, September 30', '2026-09-30 05:00:00', '5:00 AM', None),
    ('Wednesday, September 30', '2026-09-30 05:00:00', '5:00 AM CST', None),
    ('Wednesday, September 30', 'invalid', '5:00 AM EDT', None),
])
def test_time_zones_midnight_year_rollover_and_unknown_clock(day, raw, clock, expected):
    soup = BeautifulSoup(f'<div class="match-header-date"><div class="moment-tz-convert" data-moment-format="dddd, MMMM D">{day}</div><div class="moment-tz-convert" data-utc-ts="{raw}">{clock}</div></div>', 'html.parser')
    assert parse_scheduled_time(soup)['scheduled_at'] == expected


def test_real_profile_preserves_date_event_source_and_verified_roster():
    soup = BeautifulSoup((FIXTURES / 'team-context.html').read_text(encoding='utf-8'), 'html.parser')
    profile = sources.parse_profile(soup)
    assert len(profile['roster']) == 5
    assert profile['roster']['5022'] == 'Derke'
    assert profile['form'][0] == 'W (2-0) vs LOUD'
    first = profile['recent_matches'][0]
    assert first['date'] == '2026-09-30' and first['result'] == 'W'
    assert first['score'] == '2-0' and first['opponent'] == 'LOUD'
    assert first['url'].startswith('https://www.vlr.gg/753451/')
    assert 'Champions 2026' in first['event']


def test_full_roster_is_read_only_filter_independent_and_keeps_recordless_players(client, monkeypatch):
    data = record()
    data['scopes']['all']['players']['9'] = {**sources.empty_player(), 'name': 'Newcomer'}
    data['scopes']['all']['players']['8'] = player('Second', acs=230)
    data['form'] = ['W (2-0) vs Other']
    data['recent_matches'] = [{'result':'W','score':'2-0','opponent':'Other','date':'2026-09-30','event':'Champions','url':'https://www.vlr.gg/753451'}]
    db.save_analysis_team('1', data)
    db.save_analysis_team('2', data)
    forbidden = Mock(side_effect=AssertionError('Prepared roster must not scrape'))
    monkeypatch.setattr(sources, 'page', forbidden)
    reports = [client.post('/api/analyze', json={'team_a_id':'1','team_b_id':'2','event_ids':events}).json() for events in (None, ['20'])]
    assert reports[0]['roster_a'] == reports[1]['roster_a']
    assert reports[0]['form_a'] == data['form']
    assert reports[0]['recent_a'] == data['recent_matches']
    assert [p['nickname'] for p in reports[0]['roster_a']] == ['Career','Second','Newcomer']
    missing = reports[0]['roster_a'][-1]
    assert missing['available'] is False and missing['rounds'] is None and missing['acs'] is None
    assert all(p['scope'] == 'career' for p in reports[0]['roster_a'])
    forbidden.assert_not_called()
    data['scopes']['all']['career_roster_verified'] = False
    assert analysis.career_roster(data) == []


@pytest.mark.parametrize('url', ['https://owcdn.net.evil.test/img/a.png', 'https://owcdn.net:444/img/a.png', 'https://user@owcdn.net/img/a.png', 'http://owcdn.net/img/a.png', 'https://owcdn.net/img/a.svg', 'https://owcdn.net/img/a.png?url=http://localhost', 'https://owcdn.net/img/../a.png'])
def test_logo_fetch_is_limited_to_fixed_public_raster_paths(url):
    with pytest.raises(ValueError):
        logos.validate_logo_url(url)


def test_logo_endpoint_only_uses_known_team_sources_and_exports_same_origin(client, monkeypatch):
    fetch = Mock(return_value=(b'public-logo', 'image/png'))
    monkeypatch.setattr('app.main.team_logo', fetch)
    assert client.get('/api/team-logo/unknown').status_code == 400
    assert client.get('/api/team-logo/1').status_code == 404
    fetch.assert_not_called()
    data = record()
    data['logo'] = 'https://owcdn.net/img/a.png'
    db.save_analysis_team('1', data)
    response = client.get('/api/team-logo/1')
    assert response.status_code == 200 and response.content == b'public-logo'
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['x-content-type-options'] == 'nosniff'
    fetch.assert_called_once_with(data['logo'])
