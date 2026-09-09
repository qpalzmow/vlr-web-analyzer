import pytest

def test_health_check(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

def test_ssrf_protection_bad_url(client):
    res = client.get("/api/match-details?url=https://evil.com/malicious-script")
    assert res.status_code == 400
    assert "not in allowed VLR domain allowlist" in res.json()["detail"]

def test_analyze_form_empty_payload(client):
    res = client.post("/api/analyze/form", json={"team_a_id": "", "team_b_id": ""})
    assert res.status_code == 200
    data = res.json()
    assert "form_a" in data
    assert "form_b" in data
    assert data["form_a"] == []

def test_analyze_advanced_unified_schema(client):
    res = client.post("/api/analyze/advanced", json={"team_a_id": "", "team_b_id": ""})
    assert res.status_code == 200
    data = res.json()
    assert "adv_a" in data
    assert "adv_b" in data
    expected_keys = {
        "map_win_rate", "pistol_win_rate", "fk_fd_margin", "fk_fd_diff",
        "fk_fd_per_round", "total_played", "total_wins", "total_fk",
        "total_fd", "top_compositions"
    }
    assert set(data["adv_a"].keys()) == expected_keys
    assert set(data["adv_b"].keys()) == expected_keys

def test_simulate_banpick_api(client):
    payload = {
        "maps_a": {"Ascent": {"played": 5, "w": 4}},
        "maps_b": {"Ascent": {"played": 5, "w": 1}},
        "map_pool": ["Ascent", "Haven", "Lotus"]
    }
    res = client.post("/api/simulate/banpick", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "bans" in data
    assert "picks" in data

def test_cache_warmer_endpoint(client):
    res = client.post("/api/cache/warm")
    assert res.status_code == 503
    assert res.json()["detail"] == "Manual maintenance is disabled"

def test_api_404_protection(client):
    res = client.get("/api/nonexistent-endpoint")
    assert res.status_code == 404
    assert res.json() == {"detail": "API endpoint not found"}

def test_single_flight_cache():
    import time
    from concurrent.futures import ThreadPoolExecutor
    from app.cache import get_cached_data, CACHE
    
    call_count = 0
    def slow_fetch():
        nonlocal call_count
        call_count += 1
        time.sleep(0.1)
        return {"result": 42}
    
    # Run 10 parallel requests on cold cache key
    key = f"test_single_flight_{time.time()}"
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(get_cached_data, 'matches', key, slow_fetch) for _ in range(10)]
        results = [f.result() for f in futures]
    
    # Assert all 10 got the exact same result, but slow_fetch was called exactly ONCE!
    assert all(r == {"result": 42} for r in results)
    assert call_count == 1
