"""Hourly, atomically published selection data. HTTP readers never scrape VLR."""
import copy
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.db import (get_catalog_snapshot, save_catalog_snapshot, get_sync_status,
                    set_sync_status, save_team_data)
from app.scraper.vlr import get_matches, get_match_details, get_team_events, get_event_map_pool
from app.scraper.http import validate_vlr_url
from app.sync_lease import sync_lease

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 3600
SCHEMA_VERSION = 1
_stop = threading.Event()
_worker = None
_analytics_worker = None
_analytics_lock = threading.Lock()


def utcnow():
    return datetime.now(timezone.utc)


def match_id(match):
    value = str(match.get("id") or "")
    if not value:
        value = urlparse(match.get("url") or match.get("match_url") or "").path.strip("/").split("/")[0]
    return value if value.isdigit() else ""


def _collect(keys, fetch, failures, kind):
    results = {}
    # Bounded I/O concurrency; no dependency on analytics workers or API traffic.
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="vlr-catalog") as pool:
        jobs = {pool.submit(fetch, key): key for key in dict.fromkeys(keys)}
        for future in as_completed(jobs):
            key = jobs[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                logger.warning("Catalog %s %s: %s", kind, key, exc)
                failures.append({"kind": kind, "id": str(key)})
    return results


def build_snapshot(previous=None):
    previous = previous or {}
    previous_matches = {match_id(m): m for m in previous.get("matches", [])}
    failures = []
    matches = get_matches(strict=True)
    if not matches:
        raise ValueError("No match catalog collected; keeping the previous snapshot")
    # Strip legacy enrichment and browser state from the source catalog.
    matches = [{k: v for k, v in m.items() if k not in
                {"selection_data", "team_a_events", "team_b_events", "selection_cached_at"}}
               for m in matches if match_id(m)]
    matches = list({match_id(m): m for m in matches}.values())
    if not matches:
        raise ValueError("No valid matches collected")
    urls = {}
    for m in matches:
        m["id"] = match_id(m)
        urls[m["id"]] = validate_vlr_url(m.get("url") or m.get("match_url") or m["id"])
        m["url"] = urls[m["id"]]
    details = _collect(urls.values(), get_match_details, failures, "match")
    team_ids = [str(d[k]) for d in details.values() for k in ("team_a_id", "team_b_id") if d.get(k)]
    # Fresh once per team per generation, including genuinely empty event menus.
    menus = _collect(team_ids, lambda tid: get_team_events(tid, strict=True), failures, "team")
    for tid, events in menus.items():
        save_team_data(tid, events_data=events)
    event_ids = [str(d["event_id"]) for d in details.values() if d.get("event_id")]
    pools = _collect(event_ids, get_event_map_pool, failures, "pool")
    collected_at = utcnow().isoformat()
    for m in matches:
        prior = previous_matches.get(m["id"], {}).get("selection_data")
        d = details.get(m["url"])
        a, b = (str(d.get("team_a_id") or ""), str(d.get("team_b_id") or "")) if d else ("", "")
        if d and a and b and a in menus and b in menus:
            event_id = str(d.get("event_id") or "")
            old_pool = (prior or {}).get("map_pool", []) if (prior or {}).get("details", {}).get("event_id") == d.get("event_id") else []
            m["selection_data"] = {
                "details": d, "team_a_events": menus[a][:12], "team_b_events": menus[b][:12],
                "map_pool": pools.get(event_id) or old_pool,
                "live_score": None, "cached": True, "collected_at": collected_at, "stale": False,
            }
        elif prior and (not d or (a == str(prior["details"].get("team_a_id")) and
                                  b == str(prior["details"].get("team_b_id")))):
            # Never pair the prior teams' menus with a newly assigned matchup.
            m["selection_data"] = {**copy.deepcopy(prior), "stale": True}
        m["selection_status"] = ("ready" if m.get("selection_data") else
                                 "unassigned" if d and (not a or not b) else "pending")
    ready = sum(m["selection_status"] == "ready" for m in matches)
    if not ready and previous.get("ready_count", 0):
        raise ValueError("No ready selections collected; keeping the previous snapshot")
    return {"schema_version": SCHEMA_VERSION, "generation": uuid.uuid4().hex,
            "updated_at": collected_at, "refresh_interval_seconds": INTERVAL_SECONDS,
            "matches": matches, "ready_count": ready,
            "pending_count": sum(m["selection_status"] == "pending" for m in matches),
            "unassigned_count": sum(m["selection_status"] == "unassigned" for m in matches),
            "failures": failures}


def read_catalog():
    snapshot = get_catalog_snapshot() or {
        "schema_version": SCHEMA_VERSION, "generation": None, "updated_at": None,
        "matches": [], "ready_count": 0, "pending_count": 0,
        "refresh_interval_seconds": INTERVAL_SECONDS,
    }
    status = get_sync_status()
    snapshot["sync_status"] = status.get("status", "pending")
    snapshot["next_refresh_at"] = status.get("details", {}).get("next_refresh_at")
    return snapshot


def read_selection(url):
    clean_url = validate_vlr_url(url)
    wanted = match_id({"url": clean_url})
    for match in (get_catalog_snapshot() or {}).get("matches", []):
        if wanted and match_id(match) == wanted:
            return match.get("selection_data")
    return None


def bootstrap_snapshot():
    # Bundled public data makes a fresh deployment usable while its first sync runs.
    # A persistent database always takes precedence over the deployment seed.
    if get_catalog_snapshot():
        return
    seed = Path(__file__).resolve().parents[1] / "data" / "catalog_seed.json"
    if seed.exists():
        try:
            payload = json.loads(seed.read_text(encoding="utf-8"))
            if payload.get("schema_version") == SCHEMA_VERSION and payload.get("ready_count", 0):
                save_catalog_snapshot(payload)
        except Exception:
            logger.exception("Could not load catalog seed")


def queue_analytics(matches):
    global _analytics_worker
    with _analytics_lock:
        if _analytics_worker and _analytics_worker.is_alive():
            return
        def work():
            from app.sync import sync_single_team
            teams = {}
            for m in matches:
                d = m.get("selection_data", {}).get("details", {})
                for side in ("a", "b"):
                    if d.get(f"team_{side}_id"):
                        teams[str(d[f"team_{side}_id"])] = d.get(f"team_{side}_name", "")
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="vlr-analytics") as pool:
                # Small batches allow shutdown between teams; analytics never hold the catalog lease.
                entries = list(teams.items())
                for i in range(0, len(entries), 2):
                    if _stop.is_set():
                        return
                    list(pool.map(lambda item: sync_single_team(*item), entries[i:i + 2]))
        _analytics_worker = threading.Thread(target=work, daemon=True, name="VLRAnalyticsWarmup")
        _analytics_worker.start()


def refresh_catalog():
    with sync_lease() as acquired:
        if not acquired:
            return {"status": "already_running"}
        started = utcnow()
        meta = {"started_at": started.isoformat(), "catalog_schema": SCHEMA_VERSION,
                "next_refresh_at": (started + timedelta(seconds=INTERVAL_SECONDS)).isoformat()}
        set_sync_status("running", meta)
        try:
            payload = build_snapshot(get_catalog_snapshot())
            save_catalog_snapshot(payload)
            meta.update({"ready_count": payload["ready_count"], "pending_count": payload["pending_count"],
                         "completed_at": utcnow().isoformat()})
            status = "degraded" if payload["failures"] or payload["pending_count"] else "completed"
            set_sync_status(status, meta)
            queue_analytics(payload["matches"])
            return {"status": status, "details": meta}
        except Exception:
            logger.exception("Catalog refresh failed; previous snapshot remains available")
            meta["next_refresh_at"] = (utcnow() + timedelta(minutes=5)).isoformat()
            set_sync_status("error", meta)
            return {"status": "error", "details": meta}


def refresh_due(status, now=None):
    now = now or utcnow()
    meta = status.get("details", {})
    if meta.get("catalog_schema") != SCHEMA_VERSION:
        return True
    if status.get("status") == "running":
        return True  # The renewable lease decides whether a crashed run can be recovered.
    try:
        return now >= datetime.fromisoformat(meta["next_refresh_at"])
    except (KeyError, TypeError, ValueError):
        return True


def _scheduler_loop():
    while not _stop.is_set():
        try:
            if refresh_due(get_sync_status()):
                refresh_catalog()
        except Exception:
            logger.exception("Catalog scheduler failed")
        _stop.wait(15)


def start_catalog_scheduler():
    global _worker
    bootstrap_snapshot()
    if _worker is None or not _worker.is_alive():
        _stop.clear()
        _worker = threading.Thread(target=_scheduler_loop, daemon=True, name="VLRHourlyCatalog")
        _worker.start()


def stop_catalog_scheduler():
    _stop.set()
    if _worker:
        _worker.join(timeout=2)
