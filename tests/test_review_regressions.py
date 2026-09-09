import json
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.db as db
import app.main as main
import app.sync as sync
import app.sync_lease as lease
from app.schemas import TeamAnalysisPayload


def test_cached_match_has_unknown_score_until_explicit_score_request(client, monkeypatch):
    url = "https://www.vlr.gg/999999/test"
    db.save_cached_match_details(url, {"team_a_id": "1", "team_b_id": "2"})
    fetch = Mock(return_value={"status": "live", "series_score_a": "1", "series_score_b": "0", "maps": []})
    monkeypatch.setattr(main, "get_live_score", fetch)
    response = client.get("/api/match-details", params={"url": url})
    assert response.json()["live_score"] is None
    fetch.assert_not_called()
    response = client.get("/api/live-score", params={"url": url})
    assert response.json()["status"] == "live"
    fetch.assert_called_once_with(url)


def test_live_score_normalizes_relative_url(client, monkeypatch):
    fetch = Mock(return_value={"status": "final"})
    monkeypatch.setattr(main, "get_live_score", fetch)
    assert client.get("/api/live-score", params={"url": "/123456"}).status_code == 200
    fetch.assert_called_once_with("https://www.vlr.gg/123456")


def test_sync_stores_all_time_scope(monkeypatch):
    maps = Mock(return_value={"Ascent": {"played": 100, "w": 60}})
    player = Mock(return_value={"rounds": 20, "weighted_acs": 4000, "kills": 10, "deaths": 8})
    advanced = Mock(return_value={"total_played": 100})
    monkeypatch.setattr(sync, "get_team_events", lambda _: [{"id": str(i)} for i in range(4)])
    monkeypatch.setattr(sync, "get_team_form", lambda *a, **kw: ["W"])
    monkeypatch.setattr(sync, "get_team_maps_stats", maps)
    monkeypatch.setattr(sync, "get_team_roster", lambda _: [{"id": "10", "name": "Player"}])
    monkeypatch.setattr(sync, "get_player_stats", player)
    monkeypatch.setattr(sync, "get_team_advanced_metrics", advanced)
    assert sync.sync_single_team("1")
    maps.assert_called_once_with("1", None)
    player.assert_called_once_with("10", None)
    advanced.assert_called_once_with("1", None)
    assert main._get_maps_for_team("1")["Ascent"]["played"] == 100


def test_filtered_empty_results_never_use_all_time_cache(monkeypatch):
    db.save_team_data("1", maps_data={"Ascent": {"played": 100}},
                      ace_data={"nickname": "Other event", "acs": 300},
                      advanced_data={"total_played": 100})
    monkeypatch.setattr(main, "get_team_maps_stats", lambda *a: {})
    monkeypatch.setattr(main, "get_team_roster", lambda *a: [])
    monkeypatch.setattr(main, "get_team_advanced_metrics", lambda *a: {"total_played": 0})
    assert main._get_maps_for_team("1", ["999"]) == {}
    assert main._get_ace_for_team("1", ["999"])["nickname"] == "N/A"
    assert main._get_advanced_for_team("1", ["999"])["total_played"] == 0


def test_expired_fields_do_not_become_fresh_when_another_field_is_saved(monkeypatch):
    db.save_team_data("1", maps_data={"Ascent": {"played": 100}}, form_data=["L"])
    conn = db.get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE team_data SET maps_updated_at = ?",
                         ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),))
    finally:
        conn.close()
    db.save_team_data("1", form_data=["W"])
    assert db.get_cached_team_data("1")["form"] == ["W"]
    assert db.get_cached_team_data("1")["maps"] == {}
    fetch = Mock(return_value={"Bind": {"played": 1}})
    monkeypatch.setattr(main, "get_team_maps_stats", fetch)
    assert main._get_maps_for_team("1") == {"Bind": {"played": 1}}
    fetch.assert_called_once()


def test_legacy_schema_migration_expires_ambiguous_scope(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE team_data (
            team_id TEXT PRIMARY KEY, team_name TEXT, maps_json TEXT,
            form_json TEXT, ace_json TEXT, advanced_json TEXT,
            events_json TEXT, updated_at TEXT)""")
        conn.execute("INSERT INTO team_data(team_id,maps_json,updated_at) VALUES(?,?,?)",
                     ("1", json.dumps({"Ascent": {"played": 3}}), datetime.now(timezone.utc).isoformat()))
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    db.init_db()  # Additive migration is repeatable.
    assert db.get_cached_team_data("1")["maps"] == {}
    db.save_team_data("1", maps_data={"Ascent": {"played": 100}})
    assert db.get_cached_team_data("1")["maps"]["Ascent"]["played"] == 100


def test_event_union_of_two_twelve_item_lists_is_accepted(client, monkeypatch):
    events = [str(i) for i in range(1, 25)]
    monkeypatch.setattr(main, "_get_maps_for_team", lambda *a: {})
    response = client.post("/api/analyze/maps", json={"team_a_id": "1", "event_ids": events})
    assert response.status_code == 200
    with pytest.raises(ValueError):
        TeamAnalysisPayload(event_ids=events + ["25"])


def test_live_lease_blocks_second_process_and_expired_lease_can_be_claimed(monkeypatch):
    monkeypatch.setattr(lease, "time", SimpleNamespace(time=lambda: 1000))
    assert lease._claim("old-owner")
    assert not lease._claim("new-owner")
    monkeypatch.setattr(lease, "time", SimpleNamespace(time=lambda: 1400))
    assert lease._claim("new-owner")
    lease._renew("old-owner")  # A stale owner cannot renew someone else's lease.
    conn = db.get_db_connection()
    try:
        row = conn.execute("SELECT owner, expires_at FROM sync_lease").fetchone()
        assert row["owner"] == "new-owner"
        assert row["expires_at"] == 1700
    finally:
        conn.close()


def test_sync_lease_is_released_even_on_exception():
    with pytest.raises(RuntimeError):
        with lease.sync_lease() as acquired:
            assert acquired
            raise RuntimeError("interrupted")
    with lease.sync_lease() as acquired:
        assert acquired


def test_scheduler_retries_stale_running_state(monkeypatch):
    class EndLoop(BaseException):
        pass

    def sleep(seconds):
        if seconds == 300:
            raise EndLoop()

    monkeypatch.setattr(sync, "time", SimpleNamespace(sleep=sleep))
    monkeypatch.setattr(sync, "get_sync_status", lambda: {
        "status": "running", "last_synced_at": datetime.now(timezone.utc).isoformat()})
    run = Mock()
    monkeypatch.setattr(sync, "run_daily_sync", run)
    with pytest.raises(EndLoop):
        sync._daily_scheduler_loop()
    run.assert_called_once()


@pytest.mark.parametrize("successes,expected", [([False, False], "error"), ([True, False], "degraded"), ([True, True], "completed")])
def test_sync_reports_team_failures(monkeypatch, successes, expected):
    monkeypatch.setattr(sync, "CORE_S_TIER_TEAMS", {"1": "One", "2": "Two"})
    monkeypatch.setattr(sync, "get_matches", lambda: [])
    monkeypatch.setattr(sync, "sync_single_team", lambda tid, name: successes[int(tid) - 1])
    result = sync.run_daily_sync()
    assert result["status"] == expected
    assert result["details"]["teams_synced_successfully"] == sum(successes)
    assert len(result["details"].get("failures", [])) == successes.count(False)


def test_totally_empty_team_scrape_preserves_existing_record(monkeypatch):
    db.save_team_data("1", maps_data={"Ascent": {"played": 5}})
    for name in ("get_team_events", "get_team_form", "get_team_roster"):
        monkeypatch.setattr(sync, name, lambda *a, **kw: [])
    monkeypatch.setattr(sync, "get_team_maps_stats", lambda *a: {})
    assert not sync.sync_single_team("1")
    assert db.get_cached_team_data("1")["maps"]["Ascent"]["played"] == 5


@pytest.mark.parametrize("endpoint", ["/api/cache/warm", "/api/sync/trigger"])
def test_maintenance_authentication_and_cooldown(client, monkeypatch, endpoint):
    submit = Mock()
    monkeypatch.setattr(main, "_global_executor", SimpleNamespace(submit=submit))
    assert client.post(endpoint).status_code == 503
    monkeypatch.setenv("VLR_MAINTENANCE_TOKEN", "review-test-token")
    assert client.post(endpoint).status_code == 401
    assert client.post(endpoint, headers={"Authorization": "Bearer wrong"}).status_code == 401
    submit.assert_not_called()
    job = Future()
    submit.return_value = job
    headers = {"Authorization": "Bearer review-test-token"}
    try:
        assert client.post(endpoint, headers=headers).status_code == 200
        assert client.post(endpoint, headers=headers).status_code == 409
    finally:
        job.set_result(None)
    assert client.post(endpoint, headers=headers).status_code == 429
    assert submit.call_count == 1
