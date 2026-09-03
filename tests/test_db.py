import os
import pytest
from app.db import (
    init_db, save_team_data, get_cached_team_data,
    save_matches_cache, get_cached_matches,
    set_sync_status, get_sync_status, get_db_connection
)

def test_db_initialization_and_wal():
    init_db()
    conn = get_db_connection()
    try:
        cursor = conn.execute("PRAGMA journal_mode;")
        row = cursor.fetchone()
        # In memory or file, WAL is returned
        assert row[0].lower() in ("wal", "memory")
    finally:
        conn.close()

def test_save_and_get_team_data():
    init_db()
    team_id = "test_team_999"
    maps_data = {"Ascent": {"played": 10, "w": 7, "l": 3}}
    form_data = ["W (2-0) vs T1", "W (2-1) vs GEN"]
    ace_data = {"nickname": "f0rsakeN", "acs": 260.0, "kd_margin": 15, "agents": ["Jett", "Yoru"]}
    adv_data = {"map_win_rate": 70.0, "fk_fd_margin": 0.15, "total_played": 10}

    save_team_data(
        team_id=team_id,
        team_name="Paper Rex Test",
        maps_data=maps_data,
        form_data=form_data,
        ace_data=ace_data,
        advanced_data=adv_data
    )

    cached = get_cached_team_data(team_id)
    assert cached is not None
    assert cached["team_name"] == "Paper Rex Test"
    assert cached["maps"] == maps_data
    assert cached["form"] == form_data
    assert cached["ace"]["nickname"] == "f0rsakeN"
    assert cached["advanced"]["map_win_rate"] == 70.0

def test_matches_cache_crud():
    init_db()
    matches = [
        {"team_a": "DRX", "team_b": "PRX", "event": "VCT 2026: Pacific Stage 2"}
    ]
    save_matches_cache("s_tier", "pacific", matches)
    retrieved = get_cached_matches("s_tier", "pacific")
    assert retrieved == matches

def test_sync_status():
    init_db()
    save_team_data("100", "PRX", {"Ascent": {"w": 1, "l": 0}})
    set_sync_status("completed", {"synced": 44})
    status = get_sync_status()
    assert status["status"] == "completed"
    assert status["details"]["synced"] == 44
    assert status["synced_teams_count"] >= 1

def test_sync_status_api(client):
    res = client.get("/api/sync/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "synced_teams_count" in data
