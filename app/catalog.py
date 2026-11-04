"""Hourly, atomically published selection data. HTTP readers never scrape VLR."""
import copy
import json
import logging
import threading
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.db import (get_catalog_snapshot, save_catalog_snapshot, get_sync_status,
                    set_sync_status)
from app.scraper.vlr import get_matches, get_match_details, get_team_events, get_event_map_pool
from app.scraper.http import (CollectionBudgetExceeded, check_collection_budget,
                              validate_vlr_url)
from app.sync_lease import sync_lease
from app.config import collection_workers

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 3600
RETRY_SECONDS = 900
SCHEMA_VERSION = 1
_stop = threading.Event()
_worker = None
_analytics_worker = None
_analytics_lock = threading.Lock()
_analytics_pending = None


def utcnow():
    return datetime.now(timezone.utc)


def match_id(match):
    value = str(match.get("id") or "")
    if not value:
        value = urlparse(match.get("url") or match.get("match_url") or "").path.strip("/").split("/")[0]
    return value if value.isdigit() else ""


class CatalogCollectionError(ValueError):
    """A known collection failure with no usable previous public catalog."""

    def __init__(self, message, failures):
        super().__init__(message)
        self.failures = copy.deepcopy(failures)
        self.budget_exhausted = any(f.get("reason") == "budget_exceeded" for f in failures)


def _failure(kind, key, exc):
    reason = ("budget_exceeded" if isinstance(exc, CollectionBudgetExceeded) else
              "http_error" if isinstance(exc, (httpx.HTTPError, OSError)) else "parse_error")
    return {"kind": kind, "id": str(key), "reason": reason}


def _collect(keys, fetch, failures, kind, *, collected_at=None, on_progress=None):
    """Submit at most four requests, checking the shared budget before each one."""
    results, times = {}, collected_at if collected_at is not None else {}
    pending = iter(dict.fromkeys(keys))
    exhausted = False
    workers = collection_workers()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vlr-catalog") as pool:
        jobs = {}

        def submit():
            nonlocal exhausted
            while not exhausted and len(jobs) < workers:
                try:
                    key = next(pending)
                except StopIteration:
                    exhausted = True
                    return
                try:
                    check_collection_budget()
                except CollectionBudgetExceeded as exc:
                    failures.append(_failure(kind, key, exc))
                    failures.extend(_failure(kind, rest, exc) for rest in pending)
                    exhausted = True
                    return
                jobs[pool.submit(fetch, key)] = key

        submit()
        while jobs:
            done, _ = wait(jobs, return_when=FIRST_COMPLETED)
            for future in done:
                key = jobs.pop(future)
                try:
                    results[key] = future.result()
                    times[key] = utcnow().isoformat()
                except (CollectionBudgetExceeded, httpx.HTTPError, OSError, ValueError) as exc:
                    logger.warning("Catalog %s %s: %s", kind, key, exc)
                    failures.append(_failure(kind, key, exc))
            if on_progress:
                on_progress(results, times)
            submit()
    return results


def same_selection_identity(details, prior):
    """Names and match IDs cannot establish that old team/event data still apply."""
    old = (prior or {}).get("details") or {}
    return bool(details and all(
        str(details.get(key) or "") and str(details.get(key)) == str(old.get(key))
        for key in ("team_a_id", "team_b_id", "event_id")))


def _catalog_result(generation, started_at, completed_at, failures, status):
    return {"status": status, "catalog_generation": generation,
            "started_at": started_at, "completed_at": completed_at,
            "budget_exhausted": any(f.get("reason") == "budget_exceeded" for f in failures),
            "failures": copy.deepcopy(failures),
            "next_retry_at": ((datetime.fromisoformat(completed_at) + timedelta(seconds=RETRY_SECONDS)).isoformat()
                              if status != "completed" else None)}


def _valid_previous(previous):
    try:
        dated = datetime.fromisoformat(previous["updated_at"])
        if dated.tzinfo is None or previous.get("schema_version") != SCHEMA_VERSION or not previous.get("generation"):
            return False
        return any(m.get("selection_status") == "ready" and
                   all((m.get("selection_data") or {}).get("details", {}).get(k)
                       for k in ("team_a_id", "team_b_id")) and
                   all(isinstance(m["selection_data"].get(k), list)
                       for k in ("team_a_events", "team_b_events"))
                   for m in previous.get("matches", []))
    except (KeyError, TypeError, ValueError):
        return False


def _retain_previous(previous, failures, started_at):
    if not _valid_previous(previous):
        raise CatalogCollectionError("No valid ready catalog is available", failures)
    result = copy.deepcopy(previous)
    result["collection"] = _catalog_result(result["generation"], started_at, utcnow().isoformat(),
                                           failures, "retained_previous")
    return result


def _merge_source_rows(matches, sources, previous):
    """Reuse complete old rows only where failed source ownership is established."""
    failed = {sid for sid, source in sources.items() if source.get("status") != "completed"}
    if not failed:
        return matches, sources, False
    old_sources = previous.get("sources")
    old_matches = previous.get("matches", [])
    if not old_matches:
        return matches, sources, False
    if not isinstance(old_sources, dict) or any(not m.get("source_ids") for m in old_matches):
        return matches, sources, True
    failed.update(sid for sid in old_sources if "events" in failed and sid.startswith("event:"))
    sources = copy.deepcopy(sources)
    for sid in failed:
        old = old_sources.get(sid)
        if old:
            attempt = sources.get(sid, {})
            sources[sid] = {**copy.deepcopy(old), **attempt, "status": "failed", "stale": True,
                            "collected_at": old.get("collected_at"),
                            "match_ids": list(dict.fromkeys(old.get("match_ids", []) + attempt.get("match_ids", [])))}
    present = {match_id(m) for m in matches}
    merged = list(matches)
    for old in old_matches:
        if match_id(old) not in present and failed.intersection(old["source_ids"]):
            row = copy.deepcopy(old)
            row["retained_source"] = True
            if row.get("selection_data"):
                row["selection_data"]["stale"] = True
            merged.append(row)
    return merged, sources, False


def assemble_snapshot(matches, details, menus, pools, *, previous=None, failures=None,
                      generation=None, started_at=None, completed_at=None,
                      detail_times=None, menu_times=None, pool_times=None, sources=None,
                      in_progress=False):
    """Assemble a detached candidate; callers decide whether to validate/persist it."""
    previous, failures = previous or {}, copy.deepcopy(failures or [])
    detail_times, menu_times, pool_times = detail_times or {}, menu_times or {}, pool_times or {}
    completed_at = completed_at or utcnow().isoformat()
    started_at = started_at or completed_at
    previous_matches = {match_id(m): m for m in previous.get("matches", [])}
    rows = []
    for source in matches:
        if source.get("retained_source"):
            rows.append(copy.deepcopy(source))
            continue
        row = {k: copy.deepcopy(v) for k, v in source.items() if k not in {
            "selection_data", "team_a_events", "team_b_events", "selection_cached_at", "retained_source"}}
        prior = previous_matches.get(match_id(row), {}).get("selection_data")
        d = details.get(row["url"])
        a, b = (str(d.get("team_a_id") or ""), str(d.get("team_b_id") or "")) if d else ("", "")
        compatible = same_selection_identity(d, prior)
        if d:
            row["scheduled_at"] = d.get("scheduled_at")
            row["status_code"] = (d.get("live_score") or {}).get("status", "upcoming")
        fresh_menus = bool(a and b and a in menus and b in menus)
        if d and a and b and (fresh_menus or compatible):
            selection = ({"details": copy.deepcopy(d), "team_a_events": copy.deepcopy(menus[a][:12]),
                          "team_b_events": copy.deepcopy(menus[b][:12]), "cached": True,
                          "collected_at": max((t for t in (detail_times.get(row["url"]), menu_times.get(a),
                                                            menu_times.get(b)) if t), default=None),
                          "stale": False} if fresh_menus else copy.deepcopy(prior))
            selection.update(details=copy.deepcopy(d), live_score=copy.deepcopy(d.get("live_score")),
                             details_collected_at=detail_times.get(row["url"]), cached=True)
            selection["stale"] = not fresh_menus
            event_id = str(d.get("event_id") or "")
            if event_id in pools:
                selection["map_pool"] = copy.deepcopy(pools[event_id])
                selection["map_pool_info"] = {"event_id": event_id, "source": f"event:{event_id}",
                    "collected_at": pool_times.get(event_id), "status": "completed", "stale": False}
            elif compatible:
                selection["map_pool"] = copy.deepcopy(prior.get("map_pool", []))
                old_info = prior.get("map_pool_info") or {}
                selection["map_pool_info"] = {**copy.deepcopy(old_info), "event_id": event_id,
                    "source": old_info.get("source", "legacy_seed"),
                    "collected_at": old_info.get("collected_at"), "status": "retained_previous", "stale": True}
                selection["stale"] = True
            else:
                selection["map_pool"] = []
                selection["map_pool_info"] = {"event_id": event_id, "source": f"event:{event_id}",
                    "collected_at": None, "status": "pending" if in_progress else "failed", "stale": True}
                selection["stale"] = True
            pool_failure = next((f for f in failures if f.get("kind") == "pool" and f.get("id") == event_id), None)
            if pool_failure:
                selection["map_pool_info"]["reason"] = pool_failure["reason"]
            row["selection_data"] = selection
        row["selection_status"] = ("ready" if row.get("selection_data") else
                                   "unassigned" if d and (not a or not b) else "pending")
        rows.append(row)
    ready = sum(row.get("selection_status") == "ready" for row in rows)
    pending = sum(row.get("selection_status") == "pending" for row in rows)
    generation = generation or uuid.uuid4().hex
    status = "partial" if failures or pending or in_progress else "completed"
    return {"schema_version": SCHEMA_VERSION, "generation": generation,
            "updated_at": completed_at, "refresh_interval_seconds": INTERVAL_SECONDS,
            "matches": rows, "ready_count": ready, "pending_count": pending,
            "unassigned_count": sum(row.get("selection_status") == "unassigned" for row in rows),
            "failures": failures, "sources": copy.deepcopy(sources or {}),
            "collection": _catalog_result(generation, started_at, completed_at, failures, status)}


def build_snapshot(previous=None, on_checkpoint=None):
    previous = previous or {}
    started_at, generation = utcnow().isoformat(), uuid.uuid4().hex
    source_result = get_matches(strict=True, with_sources=True)
    if isinstance(source_result, list):  # Legacy callers/test fixtures have no source metadata.
        matches, sources, failures, required_complete = source_result, {}, [], True
    else:
        matches, sources = source_result["matches"], source_result["sources"]
        failures = copy.deepcopy(source_result.get("failures", []))
        required_complete = source_result["required_complete"]
    if not required_complete:
        return _retain_previous(previous, failures, started_at)
    matches, sources, retain = _merge_source_rows(matches, sources, previous)
    if retain:
        return _retain_previous(previous, failures, started_at)
    matches = list({match_id(m): copy.deepcopy(m) for m in matches if match_id(m)}.values())
    if not matches:
        failures.append({"kind": "source", "id": "matches", "reason": "parse_error"})
        return _retain_previous(previous, failures, started_at)
    for m in matches:
        m["id"] = match_id(m)
        m["url"] = validate_vlr_url(m.get("url") or m.get("match_url") or m["id"])
    detail_times, menu_times, pool_times, menus, pools = {}, {}, {}, {}, {}
    details = _collect((m["url"] for m in matches if not m.get("retained_source")),
                       get_match_details, failures, "match", collected_at=detail_times)
    if any(d.get("team_a_id") and d.get("team_b_id") and not d.get("event_id") for d in details.values()):
        failures.append({"kind": "pool", "id": "", "reason": "parse_error"})
    team_ids = [str(d[k]) for d in details.values() for k in ("team_a_id", "team_b_id") if d.get(k)]
    event_ids = [str(d["event_id"]) for d in details.values() if d.get("event_id")]

    def checkpoint(stage, results, times):
        if not on_checkpoint:
            return
        candidate = assemble_snapshot(matches, details, results if stage == "team" else menus,
            results if stage == "pool" else pools, previous=previous, failures=failures,
            generation=generation, started_at=started_at, detail_times=detail_times,
            menu_times=times if stage == "team" else menu_times,
            pool_times=times if stage == "pool" else pool_times, sources=sources, in_progress=True)
        if candidate["ready_count"]:
            on_checkpoint(candidate)

    menus = _collect(team_ids, lambda tid: get_team_events(tid, strict=True), failures, "team",
                     collected_at=menu_times, on_progress=lambda r, t: checkpoint("team", r, t))
    pools = _collect(event_ids, lambda eid: get_event_map_pool(eid, strict=True), failures, "pool",
                     collected_at=pool_times, on_progress=lambda r, t: checkpoint("pool", r, t))
    result = assemble_snapshot(matches, details, menus, pools, previous=previous, failures=failures,
        generation=generation, started_at=started_at, detail_times=detail_times, menu_times=menu_times,
        pool_times=pool_times, sources=sources)
    if not result["ready_count"]:
        return _retain_previous(previous, failures + [{"kind": "selection", "id": "catalog", "reason": "parse_error"}], started_at)
    if on_checkpoint:
        on_checkpoint(result)
    return result


def read_sync_status(snapshot=None):
    """Expose the installed generation, including independent local recovery."""
    from app.recovery import get_status
    snapshot = get_catalog_snapshot() if snapshot is None else snapshot
    status = get_sync_status()
    recovery = get_status()
    status['recovery'] = recovery
    if not snapshot:
        return status
    generation = snapshot.get('generation')
    details = status.setdefault('details', {})
    phases = details.get('collection') or {}
    # Keep legacy metadata only while it describes the installed catalog.
    if details.get('catalog_generation') not in (None, generation):
        phases = {}
    phases = copy.deepcopy(phases)
    for name in ('catalog', 'analysis'):
        if phases.get(name, {}).get('catalog_generation') not in (None, generation):
            phases.pop(name)
    if snapshot.get('collection'):
        phases['catalog'] = copy.deepcopy(snapshot['collection'])
    phases = _preserve_newer_analysis(phases, recovery, generation)
    if phases:
        details['collection'] = phases
    else:
        details.pop('collection', None)
    details.update(catalog_generation=generation, catalog_updated_at=snapshot.get('updated_at'))
    details['data_origin'] = snapshot.get('data_origin', details.get('source'))
    local_analysis = (recovery.get('collection') or {}).get('analysis')
    locally_repaired = (local_analysis and local_analysis.get('catalog_generation') == generation
                        and phases.get('analysis') == local_analysis)
    if (details['data_origin'] == 'render_recovery' or locally_repaired) and status.get('status') != 'running':
        details['external_sync_status'] = status.get('status')
        incomplete = any(phases.get(name, {}).get('status') in
                         {'partial', 'retained_previous', 'failed'} for name in ('catalog', 'analysis'))
        try:
            outdated = utcnow() - datetime.fromisoformat(snapshot['updated_at']) >= timedelta(minutes=75)
        except (KeyError, TypeError, ValueError):
            outdated = True
        status['status'] = 'degraded' if incomplete or outdated else 'completed'
    return status


def read_catalog():
    snapshot = get_catalog_snapshot() or {
        "schema_version": SCHEMA_VERSION, "generation": None, "updated_at": None,
        "matches": [], "ready_count": 0, "pending_count": 0,
        "refresh_interval_seconds": INTERVAL_SECONDS,
    }
    from app.analysis import analysis_status
    snapshot['analytics_status'] = analysis_status(snapshot['matches'])
    status = read_sync_status(snapshot)
    snapshot["sync_status"] = status.get("status", "pending")
    snapshot["next_refresh_at"] = status.get("details", {}).get("next_refresh_at")
    snapshot['sync_details'] = status.get('details', {})
    snapshot['recovery'] = status['recovery']
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
    global _analytics_worker, _analytics_pending
    with _analytics_lock:
        _analytics_pending = copy.deepcopy(matches)
        if _analytics_worker and _analytics_worker.is_alive():
            return
        def work():
            global _analytics_pending, _analytics_worker
            from app.analysis import refresh_analysis
            while True:
                with _analytics_lock:
                    if _stop.is_set() or _analytics_pending is None:
                        _analytics_worker = None
                        return
                    pending, _analytics_pending = _analytics_pending, None
                try:
                    refresh_analysis(pending, stop=_stop, force=True)
                except Exception:
                    logger.exception('Analysis refresh failed')
        _analytics_worker = threading.Thread(target=work, daemon=True, name='VLRAnalyticsWarmup')
        _analytics_worker.start()


def _preserve_newer_analysis(collection, previous, generation):
    """A cached feed response cannot roll the same generation's status back."""
    result = copy.deepcopy(collection or {})
    prior = (previous.get("collection") or {}).get("analysis") or {}
    incoming = result.get("analysis") or {}
    if not generation or prior.get("catalog_generation") != generation:
        return result
    if incoming and incoming.get("catalog_generation") != generation:
        return result
    try:
        old_clock = datetime.fromisoformat(prior.get("completed_at") or prior["started_at"])
        new_value = incoming.get("completed_at") or incoming.get("started_at")
        new_clock = datetime.fromisoformat(new_value) if new_value else None
        if old_clock.tzinfo is not None and (new_clock is None or
                                             (new_clock.tzinfo is not None and old_clock > new_clock)):
            result["analysis"] = copy.deepcopy(prior)
    except (KeyError, TypeError, ValueError):
        pass  # Legacy metadata with no usable clock cannot establish freshness.
    return result


def refresh_catalog():
    with sync_lease() as acquired:
        if not acquired:
            return {"status": "already_running"}
        started = utcnow()
        previous_details = get_sync_status().get("details", {})
        meta = {"started_at": started.isoformat(), "catalog_schema": SCHEMA_VERSION,
                "next_refresh_at": (started + timedelta(seconds=INTERVAL_SECONDS)).isoformat()}
        # A feed attempt does not replace the last imported data's phase clocks.
        # Keep them through running/error so a subsequent cached response cannot
        # roll back the same generation's completed analysis state.
        for key in ("collection", "catalog_generation", "catalog_updated_at"):
            if key in previous_details:
                meta[key] = copy.deepcopy(previous_details[key])
        set_sync_status("running", meta)
        try:
            from app import snapshot_feed
            if snapshot_feed.enabled():
                imported = snapshot_feed.refresh()
                meta.update(imported, source='github_hourly', completed_at=utcnow().isoformat(),
                            next_refresh_at=(utcnow() + timedelta(minutes=5)).isoformat())
                stale = utcnow() - datetime.fromisoformat(imported['catalog_updated_at']) >= timedelta(minutes=75)
                phases = _preserve_newer_analysis(imported.get('collection'), previous_details,
                                                  imported.get('catalog_generation'))
                meta.pop('collection', None)
                if phases:
                    meta['collection'] = phases
                catalog_phase = phases.get('catalog') or {}
                analysis_phase = phases.get('analysis') or {}
                phase_failed = (catalog_phase.get('status') in {'partial', 'retained_previous', 'failed'} or
                                analysis_phase.get('status') in {'partial', 'failed'} or
                                (not analysis_phase and phases.get('status') == 'partial'))
                status = 'degraded' if stale or phase_failed else 'completed'
                if stale:
                    meta['last_error'] = 'snapshot_outdated'
                set_sync_status(status, meta)
                return {'status': status, 'details': meta}
            payload = build_snapshot(get_catalog_snapshot())
            save_catalog_snapshot(payload)
            meta.update({"ready_count": payload["ready_count"], "pending_count": payload["pending_count"],
                         "completed_at": utcnow().isoformat(),
                         "catalog_generation": payload.get("generation"),
                         "catalog_updated_at": payload.get("updated_at")})
            phase = payload.get("collection") or {}
            meta.pop("collection", None)
            if phase:
                meta["collection"] = {"catalog": copy.deepcopy(phase)}
                if phase.get("next_retry_at"):
                    meta["next_refresh_at"] = phase["next_retry_at"]
            status = "degraded" if (phase.get("status") in {"partial", "retained_previous", "failed"} or
                                     payload.get("failures") or payload["pending_count"]) else "completed"
            set_sync_status(status, meta)
            if phase.get("status") != "retained_previous":
                queue_analytics(payload["matches"])
            return {"status": status, "details": meta}
        except Exception as exc:
            logger.exception("Catalog refresh failed; previous snapshot remains available")
            meta['last_error'] = type(exc).__name__
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
            # Request handlers only read stored data. A separate, bounded child
            # fills scheduling gaps without extending HTTP request latency.
            from app.recovery import maybe_start
            maybe_start()
        except Exception:
            logger.exception("Catalog scheduler failed")
        _stop.wait(15)


def start_catalog_scheduler():
    global _worker
    bootstrap_snapshot()
    if _worker is None or not _worker.is_alive():
        _stop.clear()
        from app.recovery import start
        start()
        from app.snapshot_feed import enabled
        if enabled():
            # On a cold start, load the persisted external generation before
            # accepting requests instead of exposing a weeks-old bundled seed.
            refresh_catalog()
        _worker = threading.Thread(target=_scheduler_loop, daemon=True, name="VLRHourlyCatalog")
        _worker.start()


def stop_catalog_scheduler():
    _stop.set()
    from app.recovery import stop
    stop()
    if _worker:
        _worker.join(timeout=2)
