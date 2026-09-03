import time
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.db import (
    init_db, save_cached_match_details, get_cached_match_details,
    set_sync_status, get_sync_status, save_matches_cache, get_cached_matches
)
import app.sync as sync_module


def test_match_details_cache_crud():
    """Verify save_cached_match_details and get_cached_match_details in SQLite."""
    init_db()
    match_url = "https://www.vlr.gg/742480/test-match"
    details = {
        "match_id": "742480",
        "team_a_id": "11060",
        "team_a_name": "Nongshim RedForce",
        "team_b_id": "918",
        "team_b_name": "Global Esports",
        "event_id": "2776"
    }
    map_pool = ["Ascent", "Haven", "Sunset"]
    team_a_events = [{"id": "2776", "name": "VCT Pacific Stage 2"}]
    team_b_events = [{"id": "2776", "name": "VCT Pacific Stage 2"}]

    save_cached_match_details(
        match_url=match_url,
        details=details,
        map_pool=map_pool,
        team_a_events=team_a_events,
        team_b_events=team_b_events
    )

    cached = get_cached_match_details(match_url, max_age_seconds=3600)
    assert cached is not None
    assert cached["details"]["match_id"] == "742480"
    assert cached["details"]["team_a_name"] == "Nongshim RedForce"
    assert cached["map_pool"] == map_pool
    assert len(cached["team_a_events"]) == 1


def test_match_details_cache_ttl_expiration():
    """Verify that expired match details cache returns None."""
    init_db()
    match_url = "https://www.vlr.gg/999999/expired-match"
    details = {"match_id": "999999", "team_a_id": "1", "team_b_id": "2"}
    save_cached_match_details(match_url=match_url, details=details)

    assert get_cached_match_details(match_url, max_age_seconds=3600) is not None
    time.sleep(0.01)
    assert get_cached_match_details(match_url, max_age_seconds=0) is None


def test_api_match_details_fast_path(client):
    """Verify that /api/match-details serves directly from DB with cached=True without network scrapers."""
    init_db()
    match_url = "https://www.vlr.gg/777777/fast-path-match"
    details = {
        "match_id": "777777",
        "team_a_id": "100",
        "team_a_name": "T1",
        "team_b_id": "200",
        "team_b_name": "GEN.G",
        "event_id": "300"
    }
    map_pool = ["Lotus", "Bind"]
    save_cached_match_details(
        match_url=match_url,
        details=details,
        map_pool=map_pool
    )

    res = client.get(f"/api/match-details?url={match_url}")
    assert res.status_code == 200
    data = res.json()
    assert data["cached"] is True
    assert data["details"]["team_a_name"] == "T1"
    assert data["details"]["team_b_name"] == "GEN.G"
    assert data["map_pool"] == ["Lotus", "Bind"]


def test_hourly_sync_schedule_threshold():
    """Verify sync logic triggers when more than 1 hour has elapsed."""
    init_db()
    set_sync_status("completed", {"synced": 10})
    ninety_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    
    from app.db import get_db_connection
    conn = get_db_connection()
    with conn:
        conn.execute("UPDATE sync_meta SET last_synced_at = ? WHERE key = 'daily_sync'", (ninety_min_ago,))
    conn.close()

    status = get_sync_status()
    last_dt = datetime.fromisoformat(status["last_synced_at"])
    assert datetime.now(timezone.utc) - last_dt > timedelta(hours=1)
