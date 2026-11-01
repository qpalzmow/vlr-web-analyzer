"""Catalog identity, source ownership and complete-candidate checkpoint contracts."""
import copy
from datetime import datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest

from app import catalog, db
from app.scraper.http import CollectionBudgetExceeded


OLD_TIME = "2026-10-22T01:00:00+00:00"
NEW_TIME = "2026-10-23T01:00:00+00:00"
URL = "https://www.vlr.gg/999999/test"
URL2 = "https://www.vlr.gg/999998/test"


def detail(a="1", b="2", event="20"):
    return {"team_a_id": a, "team_b_id": b, "event_id": event,
            "live_score": {"status": "upcoming"}}


def previous():
    return {"schema_version": 1, "generation": "old", "updated_at": OLD_TIME,
            "ready_count": 1, "pending_count": 0, "refresh_interval_seconds": 3600,
            "matches": [{"id": "999999", "url": URL, "selection_status": "ready",
                "selection_data": {"details": detail(), "team_a_events": [{"id": "20", "name": "Old"}],
                    "team_b_events": [], "map_pool": ["Bind"], "cached": True,
                    "collected_at": OLD_TIME, "map_pool_info": {"source": "event:20",
                        "event_id": "20", "collected_at": OLD_TIME, "stale": False, "status": "completed"}}}]}


def sources(monkeypatch, rows=None):
    monkeypatch.setattr(catalog, "get_matches", lambda **_: rows or [
        {"id": "999999", "url": URL}, {"id": "999998", "url": URL2}])
    monkeypatch.setattr(catalog, "get_match_details", lambda _: detail())
    monkeypatch.setattr(catalog, "get_team_events", lambda _tid, **_: [])
    monkeypatch.setattr(catalog, "get_event_map_pool", lambda _eid, **_: ["Haven"])


def test_changed_opponent_with_detail_budget_failure_stays_pending(monkeypatch):
    sources(monkeypatch)
    def fetch(url):
        if url == URL:
            raise CollectionBudgetExceeded("budget exhausted before changed matchup details")
        return detail("3", "4")
    monkeypatch.setattr(catalog, "get_match_details", fetch)
    old = previous()
    result = catalog.build_snapshot(old)
    changed = result["matches"][0]
    assert changed["selection_status"] == "pending"
    assert "selection_data" not in changed
    assert result["ready_count"] == 1
    assert result["collection"]["status"] == "partial"
    assert result["collection"]["budget_exhausted"] is True
    assert {"kind": "match", "id": URL, "reason": "budget_exceeded"} in result["failures"]
    assert old == previous()  # Assembly never mutates prior public data.


def test_same_identity_menu_failure_reuses_actual_old_time(monkeypatch):
    sources(monkeypatch)
    monkeypatch.setattr(catalog, "get_team_events", Mock(side_effect=httpx.ConnectError("offline")))
    old = previous()
    result = catalog.build_snapshot(old)
    selection = result["matches"][0]["selection_data"]
    assert selection["details"]["team_a_id"] == "1"
    assert selection["team_a_events"] == old["matches"][0]["selection_data"]["team_a_events"]
    assert selection["collected_at"] == OLD_TIME
    assert selection["stale"] is True
    assert selection["map_pool"] == ["Haven"]
    assert selection["map_pool_info"]["status"] == "completed"
    assert selection["map_pool_info"]["collected_at"] != OLD_TIME
    assert result["matches"][1]["selection_status"] == "pending"


@pytest.mark.parametrize("new_detail", [detail("2", "1"), detail(event="21"), detail("3", "2")])
def test_side_event_or_team_change_never_reuses_selection_or_pool(monkeypatch, new_detail):
    sources(monkeypatch)
    monkeypatch.setattr(catalog, "get_match_details", lambda url: new_detail if url == URL else detail("7", "8"))
    monkeypatch.setattr(catalog, "get_team_events", lambda tid, **_: [] if tid in {"7", "8"} else
                        (_ for _ in ()).throw(httpx.ConnectError("offline")))
    monkeypatch.setattr(catalog, "get_event_map_pool", Mock(side_effect=httpx.ConnectError("offline")))
    result = catalog.build_snapshot(previous())
    assert result["matches"][0]["selection_status"] == "pending"
    assert "selection_data" not in result["matches"][0]
    assert result["matches"][1]["selection_data"]["map_pool"] == []
    assert result["matches"][1]["selection_data"]["map_pool_info"]["collected_at"] is None


@pytest.mark.parametrize("outcome, reason", [(None, None), (httpx.ReadTimeout("offline"), "http_error"),
                                            (CollectionBudgetExceeded("budget"), "budget_exceeded")])
def test_empty_pool_and_failures_are_distinct_without_new_timestamps(monkeypatch, outcome, reason):
    sources(monkeypatch)
    old = previous()
    if outcome is None:
        monkeypatch.setattr(catalog, "get_event_map_pool", lambda _eid, **_: [])
    else:
        monkeypatch.setattr(catalog, "get_event_map_pool", Mock(side_effect=outcome))
    result = catalog.build_snapshot(old)
    selection = result["matches"][0]["selection_data"]
    info = selection["map_pool_info"]
    if reason is None:
        assert selection["map_pool"] == []
        assert info["status"] == "completed" and info["stale"] is False
        assert info["collected_at"] is not None and info["collected_at"] != OLD_TIME
        assert result["collection"]["status"] == "completed"
        assert result["failures"] == []
    else:
        assert selection["map_pool"] == ["Bind"]
        assert info["status"] == "retained_previous" and info["stale"] is True
        assert info["collected_at"] == OLD_TIME and info["reason"] == reason
        assert {"kind": "pool", "id": "20", "reason": reason} in result["failures"]
        assert result["collection"]["status"] == "partial"


def test_legacy_seed_pool_date_remains_unknown(monkeypatch):
    sources(monkeypatch)
    old = previous()
    del old["matches"][0]["selection_data"]["map_pool_info"]
    monkeypatch.setattr(catalog, "get_event_map_pool", Mock(side_effect=httpx.ConnectError("offline")))
    result = catalog.build_snapshot(old)
    info = result["matches"][0]["selection_data"]["map_pool_info"]
    assert info["collected_at"] is None and info["source"] == "legacy_seed"
    assert info["stale"] is True


def test_successful_fresh_scopes_clear_previous_failure_metadata(monkeypatch):
    sources(monkeypatch)
    old = previous()
    old["collection"] = {"status": "partial", "budget_exhausted": True, "next_retry_at": OLD_TIME,
                         "failures": [{"kind": "pool", "id": "20", "reason": "budget_exceeded"}]}
    result = catalog.build_snapshot(old)
    assert result["collection"]["status"] == "completed"
    assert result["collection"]["budget_exhausted"] is False
    assert result["collection"]["failures"] == []
    assert result["collection"]["next_retry_at"] is None
    assert result["generation"] != "old" and result["updated_at"] != OLD_TIME


def test_budget_stops_submission_before_any_additional_work(monkeypatch):
    fetch, clock = Mock(return_value="ok"), Mock(side_effect=CollectionBudgetExceeded("expired"))
    monkeypatch.setattr(catalog, "check_collection_budget", clock)
    failures = []
    assert catalog._collect(range(8), fetch, failures, "match") == {}
    fetch.assert_not_called()
    assert failures == [{"kind": "match", "id": str(i), "reason": "budget_exceeded"} for i in range(8)]


def test_budget_expiry_does_not_queue_work_after_first_four(monkeypatch):
    fetch = Mock(side_effect=lambda key: f"result:{key}")
    clock = Mock(side_effect=[None, None, None, None, CollectionBudgetExceeded("expired")])
    monkeypatch.setattr(catalog, "check_collection_budget", clock)
    failures, times = [], {}
    result = catalog._collect(range(8), fetch, failures, "match", collected_at=times)
    assert result == {i: f"result:{i}" for i in range(4)}
    assert set(times) == set(range(4))
    assert {call.args[0] for call in fetch.call_args_list} == set(range(4))
    assert failures == [{"kind": "match", "id": str(i), "reason": "budget_exceeded"} for i in range(4, 8)]


def test_checkpoint_only_contains_complete_selection_objects(monkeypatch):
    sources(monkeypatch)
    def events(tid, **_):
        if tid == "4":
            raise CollectionBudgetExceeded("late team menu")
        return []
    monkeypatch.setattr(catalog, "get_match_details", lambda url: detail() if url == URL else detail("3", "4"))
    monkeypatch.setattr(catalog, "get_team_events", events)
    candidates = []
    result = catalog.build_snapshot(on_checkpoint=candidates.append)
    assert candidates and candidates[-1] == result
    assert len({c["generation"] for c in candidates}) == 1
    for candidate in candidates:
        assert candidate["ready_count"] >= 1
        for row in candidate["matches"]:
            if row["selection_status"] == "ready":
                selected = row["selection_data"]
                assert selected["details"]["team_a_id"] and selected["details"]["team_b_id"]
                assert isinstance(selected["team_a_events"], list)
                assert isinstance(selected["team_b_events"], list)
            else:
                assert "selection_data" not in row
        assert candidate["matches"][1]["selection_status"] == "pending"
        assert "selection_data" not in candidate["matches"][1]


def structured(optional_failure=True, required_failure=False):
    failures = ([{"kind": "source", "id": "upcoming", "reason": "http_error"}] if required_failure else
                [{"kind": "source", "id": "event:20", "reason": "http_error"}] if optional_failure else [])
    return {"matches": [{"id": "999998", "url": URL2, "source_ids": ["upcoming"]}],
            "sources": {"upcoming": {"required": True, "status": "failed" if required_failure else "completed",
                                         "match_ids": ["999998"], "collected_at": NEW_TIME},
                        "event:20": {"required": False, "status": "failed" if optional_failure else "completed",
                                     "match_ids": [], "collected_at": None}},
            "failures": failures, "required_complete": not required_failure}


def test_supplemental_failure_preserves_proven_owned_rows_only(monkeypatch):
    sources(monkeypatch)
    old = previous()
    old["matches"][0]["source_ids"] = ["event:20"]
    old["sources"] = {"event:20": {"required": False, "status": "completed",
                                   "match_ids": ["999999"], "collected_at": OLD_TIME}}
    monkeypatch.setattr(catalog, "get_matches", lambda **_: structured())
    result = catalog.build_snapshot(old)
    assert result["generation"] != "old"
    assert result["ready_count"] == 2
    retained = result["matches"][1]
    assert retained["id"] == "999999" and retained["retained_source"] is True
    assert retained["selection_data"]["collected_at"] == OLD_TIME
    assert retained["selection_data"]["stale"] is True
    assert result["sources"]["event:20"]["collected_at"] == OLD_TIME
    assert result["sources"]["event:20"]["match_ids"] == ["999999"]
    assert result["collection"]["status"] == "partial"


def test_first_catalog_can_publish_required_rows_when_supplemental_source_fails(monkeypatch):
    sources(monkeypatch)
    monkeypatch.setattr(catalog, "get_matches", lambda **_: structured())
    result = catalog.build_snapshot()
    assert result["ready_count"] == 1
    assert result["matches"][0]["id"] == "999998"
    assert result["collection"]["status"] == "partial"
    assert result["collection"]["failures"] == structured()["failures"]


@pytest.mark.parametrize("required_failure", [False, True])
def test_unknown_source_ownership_or_required_failure_retains_whole_catalog(monkeypatch, required_failure):
    sources(monkeypatch)
    old = previous()
    monkeypatch.setattr(catalog, "get_matches", lambda **_: structured(required_failure=required_failure))
    result = catalog.build_snapshot(old)
    assert result["generation"] == "old" and result["updated_at"] == OLD_TIME
    assert result["matches"] == old["matches"]
    assert result["collection"]["catalog_generation"] == "old"
    assert result["collection"]["status"] == "retained_previous"
    retry = datetime.fromisoformat(result["collection"]["next_retry_at"])
    assert retry - datetime.fromisoformat(result["collection"]["completed_at"]) == timedelta(minutes=15)


def test_first_failed_collection_has_explicit_error_and_no_empty_candidate(monkeypatch):
    monkeypatch.setattr(catalog, "get_matches", lambda **_: structured(required_failure=True))
    with pytest.raises(catalog.CatalogCollectionError) as captured:
        catalog.build_snapshot()
    assert captured.value.failures == structured(required_failure=True)["failures"]


def test_programming_error_is_not_relabelled_as_partial_success(monkeypatch):
    sources(monkeypatch)
    monkeypatch.setattr(catalog, "get_match_details", Mock(side_effect=TypeError("bad parser contract")))
    with pytest.raises(TypeError, match="bad parser contract"):
        catalog.build_snapshot(previous())


def test_local_retained_catalog_skips_analysis_and_uses_retry_time(monkeypatch):
    old = previous()
    retained = copy.deepcopy(old)
    retained["collection"] = catalog._catalog_result("old", NEW_TIME, NEW_TIME,
        [{"kind": "source", "id": "upcoming", "reason": "budget_exceeded"}], "retained_previous")
    db.save_catalog_snapshot(old)
    monkeypatch.setattr(catalog, "build_snapshot", lambda _: retained)
    warm = Mock()
    monkeypatch.setattr(catalog, "queue_analytics", warm)
    result = catalog.refresh_catalog()
    assert result["status"] == "degraded"
    warm.assert_not_called()
    assert db.get_catalog_snapshot()["generation"] == "old"
    assert db.get_sync_status()["details"]["next_refresh_at"] == retained["collection"]["next_retry_at"]


def test_render_import_status_follows_catalog_and_analysis_phases(monkeypatch):
    from app import snapshot_feed
    current = datetime.fromisoformat(NEW_TIME)
    monkeypatch.setattr(catalog, "utcnow", lambda: current)
    monkeypatch.setattr(snapshot_feed, "enabled", lambda: True)
    def imported(catalog_status="completed", analysis_status="completed"):
        return {"catalog_updated_at": NEW_TIME, "collection": {
            "catalog": {"status": catalog_status, "catalog_generation": "new"},
            "analysis": {"status": analysis_status, "catalog_generation": "new"}}}
    monkeypatch.setattr(snapshot_feed, "refresh", Mock(side_effect=[
        imported("partial"), imported("retained_previous"), imported(analysis_status="partial"), imported()]))
    for expected in ("degraded", "degraded", "degraded", "completed"):
        result = catalog.refresh_catalog()
        assert result["status"] == expected
        assert db.get_sync_status()["status"] == expected
    assert db.get_sync_status()["details"]["collection"]["catalog"]["status"] == "completed"
    assert "last_error" not in db.get_sync_status()["details"]


def test_render_keeps_newer_analysis_phase_only_for_same_generation(monkeypatch):
    from app import snapshot_feed
    current = datetime.fromisoformat(NEW_TIME)
    older = (current - timedelta(minutes=15)).isoformat()
    monkeypatch.setattr(catalog, "utcnow", lambda: current)
    monkeypatch.setattr(snapshot_feed, "enabled", lambda: True)
    def imported(generation, analysis_status, clock):
        return {"catalog_updated_at": NEW_TIME, "catalog_generation": generation, "collection": {
            "catalog": {"status": "completed", "catalog_generation": generation},
            "analysis": {"status": analysis_status, "catalog_generation": generation,
                         "started_at": clock, "completed_at": clock}}}
    refresh = Mock(side_effect=[imported("new", "completed", NEW_TIME),
                                imported("new", "partial", older),
                                imported("different", "partial", older)])
    monkeypatch.setattr(snapshot_feed, "refresh", refresh)
    assert catalog.refresh_catalog()["status"] == "completed"
    assert catalog.refresh_catalog()["status"] == "completed"
    phase = db.get_sync_status()["details"]["collection"]["analysis"]
    assert phase["status"] == "completed" and phase["completed_at"] == NEW_TIME
    assert catalog.refresh_catalog()["status"] == "degraded"
    phase = db.get_sync_status()["details"]["collection"]["analysis"]
    assert phase["catalog_generation"] == "different" and phase["status"] == "partial"


def test_render_download_error_preserves_phase_clocks_for_next_cached_import(monkeypatch):
    from app import snapshot_feed
    current = datetime.fromisoformat(NEW_TIME)
    older = (current - timedelta(minutes=15)).isoformat()
    monkeypatch.setattr(catalog, "utcnow", lambda: current)
    monkeypatch.setattr(snapshot_feed, "enabled", lambda: True)

    def imported(status, clock):
        return {"catalog_updated_at": NEW_TIME, "catalog_generation": "new", "collection": {
            "catalog": {"status": "completed", "catalog_generation": "new"},
            "analysis": {"status": status, "catalog_generation": "new",
                         "started_at": clock, "completed_at": clock}}}

    completed = imported("completed", NEW_TIME)
    calls = 0

    def refresh():
        nonlocal calls
        calls += 1
        if calls == 1:
            return completed
        running = db.get_sync_status()
        assert running["status"] == "running"
        assert running["details"]["collection"] == completed["collection"]
        assert running["details"]["catalog_generation"] == "new"
        assert running["details"]["catalog_updated_at"] == NEW_TIME
        if calls == 2:
            raise httpx.ConnectError("feed temporarily unavailable")
        return imported("partial", older)

    monkeypatch.setattr(snapshot_feed, "refresh", refresh)
    assert catalog.refresh_catalog()["status"] == "completed"
    assert catalog.refresh_catalog()["status"] == "error"
    failed = db.get_sync_status()["details"]
    assert failed["collection"] == completed["collection"]
    assert failed["catalog_generation"] == "new"
    assert failed["last_error"] == "ConnectError"
    assert catalog.refresh_catalog()["status"] == "completed"
    recovered = db.get_sync_status()["details"]
    assert recovered["collection"]["analysis"] == completed["collection"]["analysis"]
    assert "last_error" not in recovered
