from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock

import pytest
import app.catalog as catalog
import app.db as db
import app.main as main
import app.scraper.vlr as vlr


def snapshot(generation="old"):
    return {"schema_version": 1, "generation": generation, "updated_at": "2020-01-01T00:00:00+00:00",
            "refresh_interval_seconds": 3600, "ready_count": 1, "pending_count": 0,
            "matches": [{"id": "999999", "url": "https://www.vlr.gg/999999/test", "selection_status": "ready",
                         "selection_data": {"details": {"team_a_id": "1", "team_b_id": "2", "event_id": "20"},
                                            "team_a_events": [{"id": "20", "name": "Event"}],
                                            "team_b_events": [], "map_pool": ["Bind"], "cached": True}}]}


def mock_sources(monkeypatch):
    monkeypatch.setattr(catalog, "queue_analytics", Mock())
    monkeypatch.setattr(catalog, "get_matches", lambda **_: [
        {"id": str(999999 + i), "url": f"https://www.vlr.gg/{999999 + i}/test"} for i in range(3)])
    monkeypatch.setattr(catalog, "get_match_details", lambda _: {
        "team_a_id": "1", "team_b_id": "2", "event_id": "20"})
    events, pool = Mock(return_value=[{"id": "20", "name": "Fresh"}]), Mock(return_value=["Haven"])
    monkeypatch.setattr(catalog, "get_team_events", events)
    monkeypatch.setattr(catalog, "get_event_map_pool", pool)
    return events, pool


def test_selection_endpoints_never_scrape_or_expire_last_snapshot(client, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Selection must not access VLR"))
    for module in (main, catalog):
        for name in ("get_matches", "get_match_details", "get_team_events", "get_event_map_pool"):
            monkeypatch.setattr(module, name, forbidden)
    assert client.get("/api/catalog").json()["matches"] == []
    assert client.get("/api/matches").json() == []
    db.save_catalog_snapshot(snapshot())
    assert client.get("/api/catalog").json()["generation"] == "old"
    assert len(client.get("/api/matches").json()) == 1
    result = client.get("/api/match-details", params={"url": "/999999"})
    assert result.status_code == 200
    assert result.json()["team_a_events"][0]["id"] == "20"
    assert client.get("/api/match-map-pool", params={"url": "/999999"}).json() == {"map_pool": ["Bind"]}
    for endpoint in ("/api/match-details", "/api/match-map-pool"):
        assert client.get(endpoint, params={"url": "/123"}).status_code == 409
    forbidden.assert_not_called()


def test_each_generation_refreshes_each_team_and_event_once(monkeypatch):
    events, pool = mock_sources(monkeypatch)
    first = catalog.build_snapshot()
    assert first["ready_count"] == 3
    assert (events.call_count, pool.call_count) == (2, 1)
    second = catalog.build_snapshot(first)
    assert second["generation"] != first["generation"]
    assert (events.call_count, pool.call_count) == (4, 2)


def test_atomic_publish_keeps_old_readers_and_prevents_overlapping_updates(client, monkeypatch):
    db.save_catalog_snapshot(snapshot())
    entered, finish = Event(), Event()
    def build(_):
        entered.set()
        assert finish.wait(5)
        return {**snapshot("new"), "failures": []}
    monkeypatch.setattr(catalog, "build_snapshot", build)
    monkeypatch.setattr(catalog, "queue_analytics", Mock())
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(catalog.refresh_catalog)
        try:
            assert entered.wait(5)
            assert client.get("/api/catalog").json()["generation"] == "old"
            assert catalog.refresh_catalog()["status"] == "already_running"
        finally:
            finish.set()
        assert task.result()["status"] == "completed"
    assert client.get("/api/catalog").json()["generation"] == "new"


def test_failed_refresh_preserves_data_and_retries(monkeypatch):
    db.save_catalog_snapshot(snapshot())
    monkeypatch.setattr(catalog, "build_snapshot", Mock(side_effect=RuntimeError("offline")))
    assert catalog.refresh_catalog()["status"] == "error"
    assert db.get_catalog_snapshot()["generation"] == "old"
    status = db.get_sync_status()
    due = datetime.fromisoformat(status["details"]["next_refresh_at"])
    assert not catalog.refresh_due(status, due - timedelta(seconds=1))
    assert catalog.refresh_due(status, due)


def test_partial_failure_reuses_only_the_same_matchup(monkeypatch):
    mock_sources(monkeypatch)
    monkeypatch.setattr(catalog, "get_team_events", Mock(side_effect=RuntimeError("offline")))
    result = catalog.build_snapshot(snapshot())
    assert result["matches"][0]["selection_data"]["stale"] is True
    assert result["matches"][1]["selection_status"] == "pending"
    monkeypatch.setattr(catalog, "get_match_details", lambda _: {"team_a_id": "3", "team_b_id": "2"})
    prior = snapshot()
    prior["ready_count"] = 0
    assert "selection_data" not in catalog.build_snapshot(prior)["matches"][0]


def test_empty_upstream_cannot_wipe_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "get_matches", lambda **_: [])
    with pytest.raises(ValueError):
        catalog.build_snapshot(snapshot())


def test_hourly_deadline_is_based_on_start_not_completion():
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    status = {"status": "completed", "last_synced_at": (start + timedelta(minutes=40)).isoformat(),
              "details": {"catalog_schema": 1, "next_refresh_at": (start + timedelta(hours=1)).isoformat()}}
    assert not catalog.refresh_due(status, start + timedelta(minutes=59))
    assert catalog.refresh_due(status, start + timedelta(hours=1))
    assert catalog.refresh_due({"status": "running", "details": {"catalog_schema": 1}}, start)


def test_busy_analytics_does_not_prevent_catalog_refresh(monkeypatch):
    queue = catalog.queue_analytics
    mock_sources(monkeypatch)
    monkeypatch.setattr(catalog, "queue_analytics", queue)
    monkeypatch.setattr(catalog, "_analytics_worker", Mock(is_alive=lambda: True))
    assert catalog.refresh_catalog()["status"] == "completed"
    assert db.get_catalog_snapshot()["ready_count"] == 3


def test_strict_events_distinguish_failed_scrape_from_empty_menu(monkeypatch):
    monkeypatch.setattr(vlr, "request_with_retry", lambda _: Mock(status_code=200, text='<select name="event_id"><option value="all">All Events</option></select>'))
    assert vlr.get_team_events("1", strict=True) == []
    for status, html in ((503, "Unavailable"), (200, "Missing")):
        monkeypatch.setattr(vlr, "request_with_retry", lambda _: Mock(status_code=status, text=html))
        with pytest.raises(ValueError):
            vlr.get_team_events("1", strict=True)


def test_static_assets_revalidate_after_deployment(client):
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/api/catalog").headers["cache-control"] == "no-store"
    assert 'api.js?v=20260914.1' in client.get("/").text


def test_catalog_source_failure_is_not_a_successful_empty_or_partial_result(monkeypatch):
    monkeypatch.setattr(vlr, "request_with_retry", Mock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError):
        vlr.get_matches(strict=True)


def test_bootstrap_uses_seed_only_when_no_persistent_snapshot_exists():
    catalog.bootstrap_snapshot()
    seeded = db.get_catalog_snapshot()
    assert seeded["ready_count"] > 0
    assert all(m.get("selection_data") for m in seeded["matches"] if m["selection_status"] == "ready")
    db.save_catalog_snapshot(snapshot("persisted"))
    catalog.bootstrap_snapshot()
    assert db.get_catalog_snapshot()["generation"] == "persisted"
