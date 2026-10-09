import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import httpx
import pytest

from app import analysis, analysis_sources as sources, db
from app.scraper import http


@pytest.fixture
def paced_http(monkeypatch):
    clock = [0.0]
    monkeypatch.setenv('VLR_REQUEST_INTERVAL_SECONDS', '1')
    monkeypatch.setattr(http, '_next_request_at', 0.0)
    monkeypatch.setattr(http, '_cooldown_until', 0.0)
    monkeypatch.setattr(http, '_collection_deadline', None)
    monkeypatch.setattr(http.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(http.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return clock


def test_rate_limit_pauses_following_requests_even_when_current_request_exhausts_retries(monkeypatch, paced_http):
    starts = []
    limited = [True]
    def get(url, **kwargs):
        starts.append(paced_http[0])
        response = httpx.Response(429 if limited.pop() else 200, request=httpx.Request('GET', url),
                                  headers={'Retry-After': '30'}) if limited else httpx.Response(200, request=httpx.Request('GET', url))
        return response
    monkeypatch.setattr(http, 'get_httpx_client', lambda: Mock(get=get))
    with pytest.raises(httpx.HTTPStatusError):
        http.request_with_retry('/1', max_retries=1)
    assert http.request_with_retry('/2').status_code == 200
    assert http.request_with_retry('/3').status_code == 200
    assert starts == [0, 30, 31]


def test_collection_deadline_stops_retry_and_new_requests_without_erasing_completed_data(monkeypatch, paced_http):
    get = Mock(side_effect=lambda url, **kw: httpx.Response(429, request=httpx.Request('GET', url),
                                                           headers={'Retry-After': '30'}))
    monkeypatch.setattr(http, 'get_httpx_client', lambda: Mock(get=get))
    http.set_collection_deadline(20)
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/1')
    get.assert_called_once()
    assert paced_http[0] == 0
    http.set_collection_deadline(None)
    assert http._collection_deadline is None


def prepared():
    stamp = datetime.now(timezone.utc).isoformat()
    return {'schema_version': analysis.SCHEMA_VERSION, 'updated_at': stamp, 'last_success_at': stamp,
            'available_events': ['20', '21'], 'failed_scopes': [], 'scopes': {
                'all': {'collected_at': stamp, 'maps': {}, 'players': {'7': {'rounds': 10}},
                        'career_roster_verified': True},
                '20': {'collected_at': stamp, 'maps': {}, 'players': {}}}}


def test_missing_event_resumes_without_refetching_fresh_career_or_completed_events(monkeypatch):
    prior = prepared()
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': ['20','21']})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {'name': 'One', 'roster': {'7': 'Player'}, 'form': []})
    career = Mock(side_effect=AssertionError('Fresh career must survive incremental resume'))
    maps = Mock(return_value={})
    monkeypatch.setattr(sources, 'player_totals', career)
    monkeypatch.setattr(sources, 'event_maps', maps)
    result = analysis.prepare_team('1', ['20','21'], prior)
    career.assert_not_called()
    maps.assert_called_once_with('1', '21')
    assert result['scopes']['all'] == prior['scopes']['all']
    assert result['scopes']['20'] == prior['scopes']['20']
    assert '21' in result['scopes']


def test_new_roster_refreshes_career_even_when_previous_scope_is_fresh(monkeypatch):
    prior = prepared()
    monkeypatch.setattr(sources, 'team_overview', lambda _: {'maps': {}, 'available_events': ['20']})
    monkeypatch.setattr(sources, 'team_profile', lambda _: {'name': 'One', 'roster': {'8': 'New'}, 'form': []})
    career = Mock(return_value={'rounds': 20})
    monkeypatch.setattr(sources, 'player_totals', career)
    result = analysis.prepare_team('1', ['20'], prior)
    career.assert_called_once_with('8')
    assert set(result['scopes']['all']['players']) == {'8'}


def test_recent_team_attempt_does_not_mask_expired_scope_and_partial_failures_are_counted(monkeypatch):
    prior = prepared()
    prior['scopes']['20']['collected_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.save_analysis_team('1', prior)
    monkeypatch.setattr(analysis, 'requirements', lambda _: {'1': {'20'}})
    prepare = Mock(return_value={**copy.deepcopy(prior), 'last_error': 'scope_collection_failed'})
    monkeypatch.setattr(analysis, 'prepare_team', prepare)
    assert analysis.refresh_analysis([]) == {'updated': 0, 'failed': 1, 'total': 1}
    prepare.assert_called_once()
