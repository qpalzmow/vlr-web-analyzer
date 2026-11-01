import httpx
import pytest

from app.scraper import http, vlr


def match_html(match_id):
    return f'''<div class="wf-card"><a class="match-item" href="/{match_id}/one-vs-two">
      <span class="match-item-team-name">One</span><span class="match-item-team-name">Two</span>
      <div class="match-item-event">VCT 2026 Pacific</div></a></div>'''


EVENTS = '''<div class="events-container"><a class="event-item" href="/event/90/example">
 <span class="event-item-title">VCT 2026 Pacific</span>
 <span class="event-item-desc-item-status">Ongoing</span></a></div>'''


@pytest.fixture(autouse=True)
def no_deadline(monkeypatch):
    monkeypatch.setattr(http, '_collection_deadline', None)


def install_source_responses(monkeypatch, *, failure=None, event_failure=False):
    seen = []
    def request(url):
        seen.append(url)
        if failure and failure in url:
            return httpx.Response(503, request=httpx.Request('GET', url))
        if '/event/matches/' in url:
            if event_failure:
                raise http.CollectionBudgetExceeded('end of budget')
            html = match_html('4')
        elif url.endswith('/events'):
            html = EVENTS
        elif 'page=2' in url:
            html = match_html('3')
        elif '/results' in url:
            html = match_html('2')
        else:
            html = match_html('1')
        return httpx.Response(200, text=html, request=httpx.Request('GET', url))
    monkeypatch.setattr(vlr, 'request_with_retry', request)
    return seen


def test_optional_event_failure_preserves_all_required_lists_and_their_ownership(monkeypatch):
    seen = install_source_responses(monkeypatch, event_failure=True)
    result = vlr.get_matches(strict=True, with_sources=True)
    assert result['required_complete'] is True
    assert {row['id'] for row in result['matches']} == {'1', '2', '3'}
    assert result['failures'] == [{'kind': 'source', 'source': 'event:90',
                                   'id': 'event:90', 'reason': 'budget_exceeded'}]
    assert result['sources']['event:90']['collected_at'] is None
    for source_id, match_id in (('upcoming', '1'), ('results:1', '2'), ('results:2', '3')):
        source = result['sources'][source_id]
        assert source['status'] == 'completed'
        assert source['required'] is True
        assert source['match_ids'] == [match_id]
        assert source['collected_at']
        assert next(row for row in result['matches'] if row['id'] == match_id)['source_ids'] == [source_id]
    assert result['sources']['events']['event_ids'] == ['90']
    assert seen[-1].endswith('/event/matches/90/?series_id=all')


def test_required_failure_is_explicit_and_does_not_erase_other_completed_sources(monkeypatch):
    install_source_responses(monkeypatch, failure='page=2')
    result = vlr.get_matches(strict=True, with_sources=True)
    assert result['required_complete'] is False
    assert {row['id'] for row in result['matches']} == {'1', '2', '4'}
    assert result['sources']['results:2']['status'] == 'failed'
    assert result['sources']['results:2']['reason'] == 'http_error'
    assert result['sources']['results:2']['match_ids'] == []


def test_source_parse_error_is_distinct_from_a_verified_empty_list(monkeypatch):
    def request(url):
        html = '<html>Error</html>' if url.endswith('/matches') else '<div class="wf-card"></div>'
        if url.endswith('/events'):
            html = '<div class="events-container"></div>'
        return httpx.Response(200, text=html, request=httpx.Request('GET', url))
    monkeypatch.setattr(vlr, 'request_with_retry', request)
    result = vlr.get_matches(strict=True, with_sources=True)
    assert result['sources']['upcoming']['reason'] == 'parse_error'
    assert result['sources']['results:1']['status'] == 'completed'
    assert result['sources']['results:1']['match_ids'] == []
    assert result['sources']['results:2']['status'] == 'completed'


def test_duplicate_match_owns_multiple_source_ids(monkeypatch):
    def request(url):
        html = '<div class="events-container"></div>' if url.endswith('/events') else match_html('1')
        return httpx.Response(200, text=html, request=httpx.Request('GET', url))
    monkeypatch.setattr(vlr, 'request_with_retry', request)
    result = vlr.get_matches(strict=True, with_sources=True)
    assert len(result['matches']) == 1
    assert result['matches'][0]['source_ids'] == ['upcoming', 'results:1', 'results:2']
    assert all(result['sources'][key]['match_ids'] == ['1'] for key in result['matches'][0]['source_ids'])


def test_legacy_strict_and_best_effort_list_contracts_are_preserved(monkeypatch):
    seen = install_source_responses(monkeypatch, failure='page=2')
    with pytest.raises(httpx.HTTPStatusError):
        vlr.get_matches(strict=True)
    assert not any(url.endswith('/events') for url in seen)
    assert {row['id'] for row in vlr.get_matches()} == {'1', '2', '4'}


def test_strict_map_pool_distinguishes_empty_http_parse_and_budget_failures(monkeypatch):
    request = httpx.Request('GET', 'https://www.vlr.gg/event/agents/90')
    monkeypatch.setattr(vlr, 'request_with_retry', lambda _: httpx.Response(
        200, text='<div class="mod-map-pool"></div><footer>Haven</footer>', request=request))
    assert vlr.get_event_map_pool('90', strict=True) == []
    monkeypatch.setattr(vlr, 'request_with_retry', lambda _: httpx.Response(503, request=request))
    with pytest.raises(httpx.HTTPStatusError):
        vlr.get_event_map_pool('90', strict=True)
    assert vlr.get_event_map_pool('90') == []
    monkeypatch.setattr(vlr, 'request_with_retry', lambda _: httpx.Response(
        200, text='<html>Error</html>', request=request))
    with pytest.raises(ValueError, match='structure'):
        vlr.get_event_map_pool('90', strict=True)
    def exhausted(_):
        raise http.CollectionBudgetExceeded('expired')
    monkeypatch.setattr(vlr, 'request_with_retry', exhausted)
    with pytest.raises(http.CollectionBudgetExceeded):
        vlr.get_event_map_pool('90', strict=True)
    assert vlr.get_event_map_pool('90') == []


def test_strict_map_pool_reads_current_public_pick_rate_table(monkeypatch):
    # Structural fragment verified read-only on event/agents/3065, 2026-10-23.
    html = '''<div class="wf-card mod-dark mod-table mod-scroll">
      <table class="wf-table mod-pr-global"><tr><th>Map</th><th>#</th></tr>
      <tr class="pr-global-row"><td>Lotus</td><td>10</td></tr>
      <tr class="pr-global-row"><td>Ascent</td><td>8</td></tr></table></div>
      <footer>Haven</footer>'''
    monkeypatch.setattr(vlr, 'request_with_retry', lambda url: httpx.Response(
        200, text=html, request=httpx.Request('GET', url)))
    assert vlr.get_event_map_pool('3065', strict=True) == ['Ascent', 'Lotus']


def test_budget_exhaustion_records_unstarted_sources_without_network_calls(monkeypatch):
    requests = []
    def request(url):
        requests.append(url)
        http.set_collection_deadline(0)
        return httpx.Response(200, text=match_html('1'), request=httpx.Request('GET', url))
    monkeypatch.setattr(vlr, 'request_with_retry', request)
    result = vlr.get_matches(strict=True, with_sources=True)
    assert len(requests) == 1
    assert result['required_complete'] is False
    assert {item['reason'] for item in result['failures']} == {'budget_exceeded'}
