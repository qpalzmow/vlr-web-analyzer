from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.db as db
import app.main as main
import app.sync_lease as lease
from app.schemas import TeamAnalysisPayload


def test_cached_match_has_unknown_score_until_explicit_score_request(client, monkeypatch):
    url = "https://www.vlr.gg/999999/test"
    db.save_catalog_snapshot({"matches": [{"id": "999999", "url": url, "selection_data": {
        "details": {"team_a_id": "1", "team_b_id": "2"}, "live_score": None}}]})
    fetch = Mock(return_value={"status": "live", "series_score_a": "1", "series_score_b": "0", "maps": []})
    monkeypatch.setattr(main, "get_live_score", fetch)
    response = client.get("/api/match-details", params={"url": url})
    assert response.json()["live_score"] is None
    fetch.assert_not_called()
    response = client.get("/api/live-score", params={"url": url})
    assert response.json()["status"] == "live"
    fetch.assert_called_once_with('https://www.vlr.gg/999999')


def test_live_score_normalizes_relative_url(client, monkeypatch):
    fetch = Mock(return_value={"status": "final"})
    db.save_catalog_snapshot({'matches': [{'id': '123456', 'url': '/123456', 'selection_data': {'details': {}}}]})
    monkeypatch.setattr(main, "get_live_score", fetch)
    assert client.get("/api/live-score", params={"url": "/123456"}).status_code == 200
    fetch.assert_called_once_with("https://www.vlr.gg/123456")


def test_event_union_of_two_twelve_item_lists_is_accepted(client, monkeypatch):
    events = [str(i) for i in range(1, 25)]
    db.save_analysis_team("1", {"scopes":{"all":{"maps":{},"players":{},"collected_at":None}}, "available_events":[],"updated_at":None})
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
