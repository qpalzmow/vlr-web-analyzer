from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.scraper import http


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setenv('VLR_REQUEST_INTERVAL_SECONDS', '0')
    for name, value in (('_next_request_at', 0.0), ('_cooldown_until', 0.0),
                        ('_collection_deadline', None)):
        monkeypatch.setattr(http, name, value)
    monkeypatch.setattr(http.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(http.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(http.random, 'uniform', lambda *_: 0.1)
    return now


def use_transport(monkeypatch, handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=37)
    monkeypatch.setattr(http, 'get_httpx_client', lambda: client)
    return client


def test_request_timeout_uses_remaining_budget_without_mutating_client(monkeypatch, clock):
    observed = []
    def respond(request):
        observed.append(request.extensions['timeout'])
        return httpx.Response(200)
    client = use_transport(monkeypatch, respond)
    http.set_collection_deadline(10)
    clock[0] = 9.75
    assert http.request_with_retry('/123').status_code == 200
    assert observed == [{'connect': 0.25, 'read': 0.25, 'write': 0.25, 'pool': 0.25}]
    assert client.timeout.read == 37
    clock[0] = 10
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/124')
    assert len(observed) == 1
    client.close()


def test_pacing_is_followed_by_another_budget_check(monkeypatch, clock):
    calls = []
    client = use_transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200))
    http.set_collection_deadline(1)
    monkeypatch.setattr(http, '_wait_for_request', lambda: clock.__setitem__(0, 1))
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/123')
    assert calls == []
    client.close()


def test_429_budget_reason_and_shared_cooldown_survive_deadline_clear(monkeypatch, clock):
    starts = []
    def respond(request):
        starts.append(clock[0])
        return httpx.Response(429, headers={'Retry-After': '30'}) if len(starts) == 1 else httpx.Response(200)
    client = use_transport(monkeypatch, respond)
    http.set_collection_deadline(5)
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/123')
    assert starts == [0]
    assert http._cooldown_until == 30
    http.set_collection_deadline(None)
    assert http.request_with_retry('/124').status_code == 200
    assert starts == [0, 30]
    client.close()


def test_late_429_still_retains_cooldown(monkeypatch, clock):
    def respond(request):
        clock[0] = 2
        return httpx.Response(429, headers={'Retry-After': '30'})
    client = use_transport(monkeypatch, respond)
    http.set_collection_deadline(1)
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/123')
    http.set_collection_deadline(None)
    assert http._cooldown_until == 32
    client.close()


@pytest.mark.parametrize('failure', ['503', 'network', 'redirect'])
def test_backoff_transport_and_redirect_do_not_start_requests_after_deadline(monkeypatch, clock, failure):
    calls = []
    def respond(request):
        calls.append(str(request.url))
        if failure == '503':
            return httpx.Response(503)
        clock[0] = 1
        if failure == 'network':
            raise httpx.ReadTimeout('late response', request=request)
        return httpx.Response(302, headers={'Location': '/124'})
    client = use_transport(monkeypatch, respond)
    http.set_collection_deadline(1)
    with pytest.raises(http.CollectionBudgetExceeded):
        http.request_with_retry('/123')
    assert calls == ['https://www.vlr.gg/123']
    http.set_collection_deadline(None)
    assert http.remaining_collection_seconds() is None
    client.close()


def test_executor_workers_observe_same_remaining_budget(monkeypatch, clock):
    observations = []
    def respond(request):
        observations.append(request.extensions['timeout']['read'])
        return httpx.Response(200)
    client = use_transport(monkeypatch, respond)
    http.set_collection_deadline(4)
    clock[0] = 1
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(http.request_with_retry, '/123').result().status_code == 200
        clock[0] = 4
        with pytest.raises(http.CollectionBudgetExceeded):
            pool.submit(http.request_with_retry, '/124').result()
    assert observations == [3]
    client.close()
