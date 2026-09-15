import copy
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from bs4 import BeautifulSoup
import pytest

import app.analysis as analysis
import app.analysis_sources as sources
import app.db as db


def record():
    def scope(played, wins, rounds, acs, kills, deaths):
        return {'collected_at': '2026-09-14T00:00:00+00:00',
                'maps': {'Bind': {'played': played, 'w': wins, 'l': played-wins,
                                  'atk_won': 10, 'atk_total': rounds/2, 'def_won': 10, 'def_total': rounds/2}},
                'players': {'7': {'name':'Player','rounds':rounds,'weighted_acs':rounds*acs,
                                  'kills':kills,'deaths':deaths,'fk':3,'fd':1,'agents':{'jett':rounds}}}}
    return {'schema_version':analysis.SCHEMA_VERSION,'updated_at':'2026-09-14T00:00:00+00:00','available_events':['20','21','22'],
            'form':['W (2-0) vs Other'],'failed_scopes':[],
            'scopes': {'20':scope(1,1,20,300,30,10),'21':scope(9,3,180,100,50,40),
                       'all':scope(100,90,2000,200,3000,2000)}}


def test_selected_events_sum_counts_before_calculating_rates():
    result = analysis.aggregate_team(record(), ['21','20','20'])
    assert result['maps']['Bind']['played'] == 10
    assert result['advanced']['map_win_rate'] == 40.0
    assert result['ace']['acs'] == 120.0
    assert result['ace']['kd_margin'] == 30
    assert result['advanced']['fk_fd_margin'] == 0.02
    assert result['advanced']['total_fk'] == 6
    assert result['event_ids'] == ['20','21']


def test_nonparticipating_events_are_zero_and_missing_participating_events_are_pending():
    result = analysis.aggregate_team(record(), ['999'])
    assert result['maps'] == {}
    assert result['ace']['nickname'] == 'N/A'
    with pytest.raises(analysis.AnalysisNotReady):
        analysis.aggregate_team(record(), ['22'])
    assert analysis.aggregate_team(record(), None)['maps']['Bind']['played'] == 100


def test_unavailable_player_stats_do_not_contaminate_other_event_averages():
    data = record()
    data['scopes']['21']['players_available'] = False
    result = analysis.aggregate_team(data, ['20','21'])
    assert result['maps']['Bind']['played'] == 10
    assert result['ace']['nickname'] == 'N/A'
    assert result['advanced']['total_fk'] is None


def test_one_analysis_endpoint_is_read_only_and_includes_simulation(client, monkeypatch):
    forbidden = Mock(side_effect=AssertionError('No scraping during analysis'))
    monkeypatch.setattr(sources, 'page', forbidden)
    db.save_analysis_team('1', record())
    db.save_analysis_team('2', record())
    result = client.post('/api/analyze', json={'team_a_id':'1','team_b_id':'2','event_ids':['20','21'],
                                              'map_pool':['Bind','Haven','Lotus']})
    assert result.status_code == 200
    data = result.json()
    assert data['ace_a']['acs'] == 120.0
    assert data['form_a'] == ['W (2-0) vs Other']
    assert data['maps_b']['Bind']['played'] == 10
    assert data['probability'] == {'a':50,'b':50}
    assert data['simulation']['bans']
    assert data['event_ids'] == ['20','21']
    assert client.post('/api/analyze',json={'team_a_id':'1','team_b_id':'3'}).status_code == 409
    assert client.post('/api/analyze',json={'team_a_id':'1','team_b_id':'2','event_ids':['22']}).status_code == 409
    forbidden.assert_not_called()


def test_failed_refresh_preserves_prior_event_scope(monkeypatch):
    prior = record()
    monkeypatch.setattr(sources,'team_overview',lambda _: {'maps':{},'available_events':['20']})
    monkeypatch.setattr(sources,'team_profile',lambda _: {'name':'One','roster':{},'form':[]})
    monkeypatch.setattr(sources,'event_maps',Mock(side_effect=RuntimeError('offline')))
    result = analysis.prepare_team('1', ['20'], prior)
    assert result['scopes']['20'] == prior['scopes']['20']
    assert result['failed_scopes'] == ['20']
    assert analysis.aggregate_team(db.get_analysis_teams(['1'])['1'], ['20'])['stale'] is True


def test_opponents_event_filters_are_collected_for_both_teams():
    matches=[{'selection_data':{'details':{'team_a_id':'1','team_b_id':'2'},
                               'team_a_events':[{'id':'20'}],'team_b_events':[{'id':'21'}]}}]
    assert analysis.requirements(matches) == {'1':{'20','21'},'2':{'20','21'}}


def test_new_hour_does_not_reuse_sources_from_previous_cycle(monkeypatch):
    monkeypatch.setattr(sources,'refresh_started_at',None)
    old = sources.source('hour-test',lambda: {'value':'old'})
    monkeypatch.setattr(sources,'refresh_started_at',datetime.now(timezone.utc)+timedelta(milliseconds=1))
    assert sources.source('hour-test',lambda: {'value':'new'}) != old


def test_event_leaderboard_parser_uses_rounds_totals_and_agent_usage():
    html='''<table class="st-table"><tbody><tr><td><a href="/player/7/test">P</a></td>
    <td data-col="rnd">100</td><td data-col="acs">250</td><td data-col="k">123</td><td data-col="d">80</td>
    <td data-col="fk">20</td><td data-col="fd">10</td><td data-col="agents"><span class="st-agent"><img src="/jett.png">60%</span></td>
    </tr></tbody></table>'''
    p=sources.parse_event_players(BeautifulSoup(html,'html.parser'))['7']
    assert p['weighted_acs'] == 25000
    assert p['kills'] == 123
    assert p['agents']['jett'] == 60
    assert sources.parse_event_players(BeautifulSoup('No stats available','html.parser')) == {'_unavailable':True}
    with pytest.raises(ValueError):
        sources.parse_event_players(BeautifulSoup('Server error','html.parser'))
    with pytest.raises(ValueError):
        sources.parse_event_players(BeautifulSoup('<table class="st-table"><tbody></tbody></table>','html.parser'))


def test_current_player_table_and_staff_without_stats():
    cells = ['<img alt="Jett">','50%',100,'1.0',250,1,70,100,1,1,1,120,80,30,20,10]
    html = '<table class="st-table mod-agent-rows"><tbody><tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr></tbody></table>'
    p=sources.parse_player(BeautifulSoup(html,'html.parser'))
    assert p['weighted_acs'] == 25000
    assert p['kills'] == 120
    assert p['agents'] == {'jett':100}
    assert sources.parse_player(BeautifulSoup('<div class="player-header"><h1>Coach</h1></div>','html.parser'))['rounds'] == 0


def test_no_data_does_not_generate_probability_or_ban_predictions():
    data = record()
    db.save_analysis_team('1',data)
    db.save_analysis_team('2',data)
    result = analysis.full_analysis('1','2',['999'],['Bind','Haven'])
    assert result['probability'] is None
    assert result['simulation'] == {'bans':[],'picks':[]}


def test_career_player_source_explicitly_requests_all_time(monkeypatch):
    fetch = Mock(return_value=BeautifulSoup('<div class="player-header"><h1>Coach</h1></div>','html.parser'))
    monkeypatch.setattr(sources, 'page', fetch)
    sources.player_totals('7')
    fetch.assert_called_once_with('https://www.vlr.gg/player/7/?timespan=all')


def test_bundled_analysis_covers_every_selectable_catalog_scope(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root/'data/catalog_seed.json').read_text(encoding='utf-8'))
    seed = json.loads((root/'data/analysis_seed.json').read_text(encoding='utf-8'))
    assert seed['schema_version'] == analysis.SCHEMA_VERSION
    forbidden = Mock(side_effect=AssertionError('Bootstrap must not scrape'))
    monkeypatch.setattr(sources, 'page', forbidden)
    analysis.bootstrap_analysis()
    teams = db.get_analysis_teams()
    for tid, events in analysis.requirements(catalog['matches']).items():
        data = teams[tid]
        assert data['schema_version'] == analysis.SCHEMA_VERSION
        assert not data['failed_scopes']
        analysis.aggregate_team(data, None)
        analysis.aggregate_team(data, list(events))
        for event_id in events:
            analysis.aggregate_team(data, [event_id])
    # A deployment must preserve data already collected on a persistent disk.
    tid = next(iter(teams))
    newer = copy.deepcopy(teams[tid])
    newer['updated_at'] = '2026-09-16T00:00:00+00:00'
    db.save_analysis_team(tid, newer)
    analysis.bootstrap_analysis()
    assert db.get_analysis_teams([tid])[tid] == newer
    forbidden.assert_not_called()
