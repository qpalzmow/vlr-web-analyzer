from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

import app.main as main
import app.db as db


def test_selection_reuses_team_menus_and_skips_map_pool(client, monkeypatch):
    events = [{"id": "20", "name": "VCT test"}]
    for team_id in ("1", "2"):
        db.save_team_data(team_id, events_data=events)
    monkeypatch.setattr(main, "get_match_details", lambda _: {
        "team_a_id": "1", "team_b_id": "2", "event_id": "20"})
    events_fetch = Mock(side_effect=AssertionError("Should use DB menus"))
    pool_fetch = Mock(side_effect=AssertionError("Selection must not wait for maps"))
    monkeypatch.setattr(main, "get_team_events", events_fetch)
    monkeypatch.setattr(main, "get_event_map_pool", pool_fetch)
    result = client.get("/api/match-details", params={"url": "/999991", "include_map_pool": "false"})
    assert result.status_code == 200
    assert result.json()["team_a_events"] == events
    assert result.json()["map_pool"] == []
    events_fetch.assert_not_called()
    pool_fetch.assert_not_called()


def test_map_pool_update_preserves_event_menus(client, monkeypatch):
    url = "https://www.vlr.gg/999992/test"
    details = {"team_a_id": "1", "team_b_id": "2", "event_id": "20"}
    events = [{"id": "20", "name": "VCT test"}]
    db.save_cached_match_details(url, details, team_a_events=events, team_b_events=events)
    pool_fetch = Mock(return_value=["Bind", "Haven"])
    monkeypatch.setattr(main, "get_event_map_pool", pool_fetch)
    assert client.get("/api/match-map-pool", params={"url": url}).json()["map_pool"] == ["Bind", "Haven"]
    cached = db.get_cached_match_details(url)
    assert cached["team_a_events"] == events
    assert cached["team_b_events"] == events
    client.get("/api/match-map-pool", params={"url": url})
    pool_fetch.assert_called_once()


def test_matches_embed_menus_only_for_verified_team_ids(client, monkeypatch):
    events = [{"id": "20", "name": "VCT test"}]
    for team_id in ("1", "2"):
        db.save_team_data(team_id, events_data=events)
    url = "https://www.vlr.gg/999993/test"
    db.save_cached_match_details(url, {"team_a_id": "1", "team_b_id": "2"})
    monkeypatch.setattr(main, "get_matches", lambda: [{"id": "999993", "url": url}, {"id": "999994", "url": "/999994"}])
    result = client.get("/api/matches").json()
    assert result[0]["team_a_events"] == events
    assert result[0]["team_b_events"] == events
    assert "team_a_events" not in result[1]


def test_cached_details_use_fresher_team_menus(client):
    url = "https://www.vlr.gg/999995/test"
    db.save_cached_match_details(url, {"team_a_id": "1", "team_b_id": "2"})
    events = [{"id": "20", "name": "VCT test"}]
    db.save_team_data("1", events_data=events)
    result = client.get("/api/match-details", params={"url": url, "include_map_pool": "false"}).json()
    assert result["team_a_events"] == events


def test_old_menus_are_not_embedded():
    db.save_team_data("1", events_data=[{"id": "20", "name": "Old"}])
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE team_data SET events_updated_at = ?",
                         ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),))
    finally:
        conn.close()
    assert db.get_cached_team_events_map() == {}


def test_expired_embedded_menus_are_removed_from_memory_cached_matches(client, monkeypatch):
    events = [{"id": "20", "name": "VCT test"}]
    for team_id in ("1", "2"):
        db.save_team_data(team_id, events_data=events)
    url = "https://www.vlr.gg/999996/test"
    db.save_cached_match_details(url, {"team_a_id": "1", "team_b_id": "2"})
    monkeypatch.setattr(main, "get_matches", lambda: [{"id": "999996", "url": url}])
    assert client.get("/api/matches").json()[0]["team_a_events"] == events
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE team_data SET events_updated_at = NULL")
    finally:
        conn.close()
    assert "team_a_events" not in client.get("/api/matches").json()[0]


def test_catalog_uses_match_cache_before_team_analytics_have_synced(client, monkeypatch):
    url = "https://www.vlr.gg/999997/test"
    events = [{"id": "20", "name": "VCT test"}]
    details = {"team_a_id": "1", "team_b_id": "2", "event_id": "20"}
    db.save_cached_match_details(url, details, map_pool=["Bind"],
                                team_a_events=events, team_b_events=events)
    assert db.get_cached_team_data("1") is None
    monkeypatch.setattr(main, "get_matches", lambda: [{"id": "999997", "url": url}])
    match = client.get("/api/matches").json()[0]
    assert match["team_a_events"] == events
    assert match["selection_data"]["details"] == details
    assert match["selection_data"]["map_pool"] == ["Bind"]


def test_expired_match_cache_is_not_used_for_instant_selection(client, monkeypatch):
    url = "https://www.vlr.gg/999998/test"
    db.save_cached_match_details(url, {"team_a_id": "1", "team_b_id": "2"},
                                team_a_events=[], team_b_events=[])
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE match_details_cache SET updated_at = ?",
                         ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),))
    finally:
        conn.close()
    monkeypatch.setattr(main, "get_matches", lambda: [{"id": "999998", "url": url}])
    assert "selection_data" not in client.get("/api/matches").json()[0]


def test_static_assets_revalidate_after_deployment(client):
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/api.js").headers["cache-control"] == "no-cache"
    assert 'api.js?v=20260912.2' in client.get("/").text
