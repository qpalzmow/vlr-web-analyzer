import time
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_schema_validation_limits():
    """Verifies that invalid numeric IDs and oversized payloads are rejected by Pydantic."""
    # Bad numeric ID with letters
    res = client.post("/api/analyze/maps", json={"team_a_id": "abc123invalid", "team_b_id": "456"})
    assert res.status_code == 422

    # Exceeding max event_ids
    oversized_events = [str(i) for i in range(1, 26)]
    res = client.post("/api/analyze/maps", json={"team_a_id": "123", "team_b_id": "456", "event_ids": oversized_events})
    assert res.status_code == 422


def test_live_score_single_flight_caching():
    """Verifies that concurrent get_cached_live_score calls share a single fetch without duplicating upstream requests."""
    from app.cache import get_cached_live_score
    from concurrent.futures import ThreadPoolExecutor
    fetch_calls = 0

    def mock_fetch_live(match_url):
        nonlocal fetch_calls
        fetch_calls += 1
        time.sleep(0.05)
        return {"series_score_a": "1", "series_score_b": "0", "status": "live", "maps": []}

    with ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(get_cached_live_score, "/test/match/live_1", mock_fetch_live)
        f2 = executor.submit(get_cached_live_score, "/test/match/live_1", mock_fetch_live)
        f3 = executor.submit(get_cached_live_score, "/test/match/live_1", mock_fetch_live)

        r1 = f1.result()
        r2 = f2.result()
        r3 = f3.result()

    assert r1["series_score_a"] == "1"
    assert r2["series_score_a"] == "1"
    assert r3["series_score_a"] == "1"
    assert fetch_calls == 1
