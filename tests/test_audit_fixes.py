import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.db import (
    init_db,
    save_team_data,
    get_cached_team_data,
    save_matches_cache,
    get_cached_matches
)
from app.cache import get_cached_data
import app.sync as sync_module

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()

def test_sync_contract_and_region_filtering(monkeypatch):
    """Verifies that run_daily_sync calls get_matches with no kwargs and handles regions properly."""
    dummy_matches = [
        {"id": "1001", "url": "/1001", "match_url": "/1001", "region": "Pacific", "team_a": "DRX", "team_b": "PRX", "tier": "S-Tier"},
        {"id": "1002", "url": "/1002", "match_url": "/1002", "region": "Americas", "team_a": "SEN", "team_b": "LEV", "tier": "S-Tier"},
    ]
    
    monkeypatch.setattr(sync_module, "get_matches", lambda: dummy_matches)
    monkeypatch.setattr(sync_module, "get_match_details", lambda url: {
        "team_a_id": "111", "team_a_name": "DRX",
        "team_b_id": "222", "team_b_name": "PRX"
    })
    monkeypatch.setattr(sync_module, "sync_single_team", lambda tid, tname: True)

    result = sync_module.run_daily_sync(force=True)
    assert result["status"] == "completed"
    assert result["details"]["total_matches_indexed"] > 0
    assert result["details"]["teams_synced_successfully"] >= 2

def test_single_flight_caching_with_futures():
    """Verifies that Single-Flight with Futures shares results and doesn't duplicate fetch calls."""
    fetch_count = 0

    def mock_slow_fetch():
        nonlocal fetch_count
        fetch_count += 1
        time.sleep(0.05)
        return {"data": "ok"}

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(get_cached_data, "test_cache", "test_key", mock_slow_fetch)
        f2 = executor.submit(get_cached_data, "test_cache", "test_key", mock_slow_fetch)
        f3 = executor.submit(get_cached_data, "test_cache", "test_key", mock_slow_fetch)

        r1 = f1.result()
        r2 = f2.result()
        r3 = f3.result()

    assert r1 == {"data": "ok"}
    assert r2 == {"data": "ok"}
    assert r3 == {"data": "ok"}
    assert fetch_count == 1

def test_sqlite_atomic_coalesce_upsert():
    """Verifies that partial updates don't overwrite previously stored JSON columns."""
    team_id = "test_atomic_999"
    save_team_data(team_id=team_id, team_name="Atomic Team", maps_data={"Ascent": {"played": 5, "w": 3}})
    
    # Second update updates ONLY form_data without maps_data
    save_team_data(team_id=team_id, form_data=["W (2-0)", "W (2-1)"])

    cached = get_cached_team_data(team_id)
    assert cached is not None
    assert "Ascent" in cached["maps"]
    assert cached["maps"]["Ascent"]["played"] == 5
    assert len(cached["form"]) == 2
    assert cached["team_name"] == "Atomic Team"

def test_matches_cache_ttl_expiration():
    """Verifies that matches older than max_age_seconds return None."""
    tier = "s_tier"
    region = "test_ttl_reg"
    save_matches_cache(tier=tier, region=region, matches=[{"test": "item"}])

    # Immediate fetch succeeds
    res = get_cached_matches(tier=tier, region=region, max_age_seconds=10)
    assert res == [{"test": "item"}]

    # With 0 second TTL, it expires
    res_expired = get_cached_matches(tier=tier, region=region, max_age_seconds=0)
    assert res_expired is None

def test_schema_validation_limits():
    """Verifies that invalid numeric IDs and oversized payloads are rejected by Pydantic."""
    # Bad numeric ID with letters
    res = client.post("/api/analyze/maps", json={"team_a_id": "abc123invalid", "team_b_id": "456"})
    assert res.status_code == 422

    # Exceeding max event_ids
    oversized_events = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14"]
    res = client.post("/api/analyze/maps", json={"team_a_id": "123", "team_b_id": "456", "event_ids": oversized_events})
    assert res.status_code == 422
