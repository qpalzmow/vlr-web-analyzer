import os
import sys
import json
import logging
import traceback
import threading
import time
import secrets
from contextlib import asynccontextmanager
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import PORT, PUBLIC_DIR, PUBLIC_DIR_NORM
from app.schemas import (
    TeamAnalysisPayload, BanPickPayload, MatchDetailsResponse,
    TeamFormResponse, TeamMapsResponse, AceAnalysisResponse,
    AdvancedMetricsResponse, BanPickResponse, HealthResponse,
    UpstreamHealthResponse
)
from app.cache import get_cached_data, get_cached_live_score, make_cache_key, LIVE_SCORE_CACHE, CACHE_TTL
from app.scraper.http import close_httpx_client, request_with_retry, validate_vlr_url
from app.scraper.vlr import (
    get_matches, get_match_details, get_event_map_pool,
    get_team_events, get_live_score, get_team_form,
    get_team_maps_stats, get_team_roster, get_player_stats,
    get_team_advanced_metrics
)
from app.scraper.metrics import find_ace_player_from_stats, simulate_banpick

from app.cache_warmer import start_cache_warmer, stop_cache_warmer, warm_cache_cycle
from app.db import (
    init_db, get_cached_team_data, save_team_data,
    get_sync_status, get_cached_matches, save_matches_cache,
    get_cached_match_details, save_cached_match_details,
    get_all_cached_match_details_map
)
from app.sync import start_sync_scheduler, run_daily_sync

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_global_executor = ThreadPoolExecutor(max_workers=12, thread_name_prefix="vlr-api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_sync_scheduler()
    yield
    _global_executor.shutdown(wait=True)
    close_httpx_client()

app = FastAPI(
    title="VLR Web Analyzer API",
    version="2.1.0",
    lifespan=lifespan
)

logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _safe_future_result(future, default):
    if future is None:
        return default
    try:
        return future.result(timeout=30)
    except Exception:
        return default

def find_ace_player(roster, event_ids):
    if not roster:
        return {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]}

    def get_stats_for_player(p):
        try:
            player_cache_key = make_cache_key(p['id'], event_ids)
            stats = get_cached_data('player_stats', player_cache_key, get_player_stats, p["id"], event_ids)
            if stats:
                stats["name"] = p.get("name", "N/A")
            return stats
        except Exception:
            return None

    # Fetch stats concurrently across roster with up to 6 workers
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(get_stats_for_player, p) for p in roster]
        players_data = []
        for f in futures:
            try:
                res = f.result(timeout=10)
                if res is not None:
                    players_data.append(res)
            except Exception:
                pass

    return find_ace_player_from_stats(players_data)

@app.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}

@app.get("/health/upstream", response_model=UpstreamHealthResponse)
def upstream_health_check():
    try:
        res = request_with_retry("https://www.vlr.gg/matches", max_retries=1)
        if res.status_code == 200:
            return {"status": "ok", "vlr": "reachable"}
        return {"status": "degraded", "vlr": f"status {res.status_code}"}
    except Exception as e:
        return {"status": "degraded", "vlr": f"unreachable: {e}"}

def _get_form_for_team(team_id: str) -> list:
    if not team_id:
        return []
    cached = get_cached_team_data(team_id)
    if cached and cached.get("form"):
        return cached["form"]
    form = get_cached_data('team_form', team_id, get_team_form, team_id)
    if form:
        save_team_data(team_id, form_data=form)
    return form

def _get_maps_for_team(team_id: str, event_ids: Optional[list] = None) -> dict:
    if not team_id:
        return {}
    cached = get_cached_team_data(team_id) if not event_ids else None
    cached_maps = (cached.get("maps") or {}) if cached else {}
    if not event_ids and cached_maps:
        return cached_maps

    key = make_cache_key(team_id, event_ids)
    try:
        maps = get_cached_data('team_stats', key, get_team_maps_stats, team_id, event_ids)
    except Exception as e:
        logger.warning("Error fetching maps for team %s: %s", team_id, e)
        maps = {}

    if maps and not event_ids:
        save_team_data(team_id, maps_data=maps)
    return maps

def _get_ace_for_team(team_id: str, event_ids: Optional[list] = None) -> dict:
    fallback_ace = {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]}
    if not team_id:
        return fallback_ace
    cached = get_cached_team_data(team_id) if not event_ids else None
    cached_ace = cached.get("ace") if cached else None
    if cached_ace and cached_ace.get("nickname") != "N/A":
        fallback_ace = cached_ace
        if not event_ids:
            return cached_ace

    try:
        roster = get_cached_data('team_roster', team_id, get_team_roster, team_id)
        ace = find_ace_player(roster, event_ids)
    except Exception as e:
        logger.warning("Error fetching ace for team %s: %s", team_id, e)
        ace = None

    if ace and ace.get("nickname") != "N/A":
        if not event_ids:
            save_team_data(team_id, ace_data=ace)
        return ace
    return fallback_ace

def _get_advanced_for_team(team_id: str, event_ids: Optional[list] = None) -> dict:
    default_adv = get_team_advanced_metrics("")
    if not team_id:
        return default_adv
    cached = get_cached_team_data(team_id) if not event_ids else None
    cached_adv = cached.get("advanced") if cached else None
    if cached_adv and cached_adv.get("total_played", 0) > 0:
        default_adv = cached_adv
        if not event_ids:
            return cached_adv

    key = make_cache_key(team_id, event_ids)
    try:
        adv = get_cached_data('pistol_stats', key, get_team_advanced_metrics, team_id, event_ids)
    except Exception as e:
        logger.warning("Error fetching advanced for team %s: %s", team_id, e)
        adv = None

    if adv and not event_ids:
        save_team_data(team_id, advanced_data=adv)
    return adv or default_adv

_maintenance_lock = threading.Lock()

@app.get("/api/matches")
def api_get_matches():
    try:
        cached_matches = get_cached_matches('s_tier', 'all', max_age_seconds=600)
        is_valid_cache = (
            cached_matches and 
            len(cached_matches) > 2 and 
            not any(m.get('url') in ('/1001', '/1002') or m.get('id') in ('1001', '1002') for m in cached_matches)
        )
        if is_valid_cache:
            matches = cached_matches
        else:
            matches = get_cached_data('matches', 'matches_list', get_matches)
            save_matches_cache('s_tier', 'all', matches)

        # Enrich matches with team IDs from single fast query
        details_map = get_all_cached_match_details_map()

        # Build reverse name→id lookup from CORE_S_TIER_TEAMS for instant fallback
        from app.config import CORE_S_TIER_TEAMS
        name_to_id = {}
        for tid, tname in CORE_S_TIER_TEAMS.items():
            name_to_id[tname.lower().strip()] = tid

        for m in matches:
            m_url = m.get('url') or m.get('match_url') or ""
            m_id = m.get('id') or ""
            det = details_map.get(m_url) or details_map.get(m_id)
            if det:
                m["team_a_id"] = det.get("team_a_id")
                m["team_b_id"] = det.get("team_b_id")
                m["event_id"] = det.get("event_id")
            else:
                # Fallback: resolve team IDs from CORE_S_TIER_TEAMS by name matching
                ta_name = (m.get("team_a") or "").lower().strip()
                tb_name = (m.get("team_b") or "").lower().strip()
                if ta_name in name_to_id:
                    m["team_a_id"] = name_to_id[ta_name]
                if tb_name in name_to_id:
                    m["team_b_id"] = name_to_id[tb_name]

        return JSONResponse(content=matches)
    except Exception as e:
        logger.error("api_get_matches failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/match-details")
def api_get_match_details(url: str = Query(...)):
    try:
        clean_url = validate_vlr_url(url)

        # 1. Fast-path: Check SQLite persistent cache first (instant response < 3ms, non-blocking)
        cached_match = get_cached_match_details(clean_url, max_age_seconds=86400)
        if cached_match and cached_match.get("details"):
            now = time.time()
            in_mem_score = LIVE_SCORE_CACHE.get(clean_url)
            if in_mem_score and (now - in_mem_score[0] < CACHE_TTL):
                live_score = in_mem_score[1]
            else:
                live_score = None  # Score is fetched independently by the browser.
            return JSONResponse(content={
                "details": cached_match["details"],
                "team_a_events": cached_match.get("team_a_events", [])[:12],
                "team_b_events": cached_match.get("team_b_events", [])[:12],
                "map_pool": cached_match.get("map_pool", []),
                "live_score": live_score,
                "cached": True
            })

        # 2. Fallback: On-demand fetch and save to SQLite cache
        details = get_cached_data('match_details', clean_url, get_match_details, clean_url)

        future_a = _global_executor.submit(
            get_cached_data, 'team_events', details["team_a_id"], get_team_events, details["team_a_id"]
        ) if details.get("team_a_id") else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_events', details["team_b_id"], get_team_events, details["team_b_id"]
        ) if details.get("team_b_id") else None
        future_pool = _global_executor.submit(
            get_cached_data, 'event_map_pool', details.get("event_id"), get_event_map_pool, details.get("event_id")
        ) if details.get("event_id") else None

        team_a_events = _safe_future_result(future_a, [])[:12]
        team_b_events = _safe_future_result(future_b, [])[:12]
        map_pool = _safe_future_result(future_pool, [])
        live_score = None

        save_cached_match_details(
            match_url=clean_url,
            details=details,
            map_pool=map_pool,
            team_a_events=team_a_events,
            team_b_events=team_b_events
        )

        return JSONResponse(content={
            "details": details,
            "team_a_events": team_a_events,
            "team_b_events": team_b_events,
            "map_pool": map_pool,
            "live_score": live_score,
            "cached": False
        })
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("api_get_match_details failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/live-score")
def api_get_live_score(url: str = Query(...)):
    try:
        clean_url = validate_vlr_url(url)
        live_score = get_cached_live_score(clean_url, get_live_score)
        return JSONResponse(content=live_score)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("api_get_live_score failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analyze/form")
def api_analyze_form(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(_get_form_for_team, payload.team_a_id) if payload.team_a_id else None
        future_b = _global_executor.submit(_get_form_for_team, payload.team_b_id) if payload.team_b_id else None

        return JSONResponse(content={
            "form_a": _safe_future_result(future_a, []),
            "form_b": _safe_future_result(future_b, [])
        })
    except Exception as e:
        logger.error("api_analyze_form failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analyze/maps")
def api_analyze_maps(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(_get_maps_for_team, payload.team_a_id, payload.event_ids) if payload.team_a_id else None
        future_b = _global_executor.submit(_get_maps_for_team, payload.team_b_id, payload.event_ids) if payload.team_b_id else None

        return JSONResponse(content={
            "maps_a": _safe_future_result(future_a, {}),
            "maps_b": _safe_future_result(future_b, {})
        })
    except Exception as e:
        logger.error("api_analyze_maps failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analyze/aces")
def api_analyze_aces(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(_get_ace_for_team, payload.team_a_id, payload.event_ids) if payload.team_a_id else None
        future_b = _global_executor.submit(_get_ace_for_team, payload.team_b_id, payload.event_ids) if payload.team_b_id else None

        return JSONResponse(content={
            "ace_a": _safe_future_result(future_a, {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]}),
            "ace_b": _safe_future_result(future_b, {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]})
        })
    except Exception as e:
        logger.error("api_analyze_aces failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analyze/advanced")
def api_analyze_advanced(payload: TeamAnalysisPayload):
    try:
        default_adv = get_team_advanced_metrics("")
        future_a = _global_executor.submit(_get_advanced_for_team, payload.team_a_id, payload.event_ids) if payload.team_a_id else None
        future_b = _global_executor.submit(_get_advanced_for_team, payload.team_b_id, payload.event_ids) if payload.team_b_id else None

        return JSONResponse(content={
            "adv_a": _safe_future_result(future_a, default_adv),
            "adv_b": _safe_future_result(future_b, default_adv)
        })
    except Exception as e:
        logger.error("api_analyze_advanced failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/sync/status")
def api_get_sync_status_endpoint():
    return JSONResponse(content=get_sync_status())

@app.post("/api/sync/trigger")
def api_trigger_sync_endpoint():
    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Maintenance task already running or queued")
    try:
        future = _global_executor.submit(run_daily_sync, True)
        future.add_done_callback(lambda _: _maintenance_lock.release())
        return JSONResponse(content={"status": "sync_triggered"})
    except Exception as e:
        _maintenance_lock.release()
        logger.error("api_trigger_sync failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/simulate/banpick")
def api_simulate_banpick(payload: BanPickPayload):
    try:
        res = simulate_banpick(payload.maps_a, payload.maps_b, payload.map_pool)
        return JSONResponse(content=res)
    except Exception as e:
        logger.error("api_simulate_banpick failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/cache/warm")
def api_trigger_cache_warm():
    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Maintenance task already running or queued")
    try:
        future = _global_executor.submit(warm_cache_cycle)
        future.add_done_callback(lambda _: _maintenance_lock.release())
        return JSONResponse(content={"status": "warming_triggered"})
    except Exception as e:
        _maintenance_lock.release()
        logger.error("api_trigger_cache_warm failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/log-error")
async def api_log_error(request: Request):
    try:
        content_length = request.headers.get('content-length', '0')
        if int(content_length) > 10240:  # 10KB limit
            return JSONResponse(content={"status": "rejected", "reason": "payload too large"}, status_code=413)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(content={"status": "rejected", "reason": "invalid json"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse(content={"status": "rejected", "reason": "json object required"}, status_code=400)
        safe_fields = {k: str(v)[:500] for k, v in body.items() if k in ('message', 'source', 'lineno', 'colno', 'stack')}
        print(f"\n>>> [BROWSER ERROR LOGGED]:\n{json.dumps(safe_fields, indent=2)}\n")
        return JSONResponse(content={"status": "logged"})
    except Exception as e:
        logger.error("api_log_error failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/{file_path:path}")
def serve_static(file_path: str):
    # Do not serve index.html for nonexistent API routes
    if file_path.startswith("api/") or file_path == "api":
        raise HTTPException(status_code=404, detail="API endpoint not found")

    if not file_path or file_path == "index.html":
        target = os.path.join(PUBLIC_DIR, "index.html")
    else:
        safe_path = os.path.normpath(file_path.lstrip('/'))
        if '\x00' in safe_path or '..' in safe_path.split(os.sep):
            raise HTTPException(status_code=404, detail="Not Found")
        target = os.path.normcase(os.path.realpath(os.path.join(PUBLIC_DIR, safe_path)))
        try:
            is_sub = os.path.commonpath([PUBLIC_DIR_NORM]) == os.path.commonpath([PUBLIC_DIR_NORM, target])
        except Exception:
            is_sub = False
        if not is_sub:
            raise HTTPException(status_code=404, detail="Not Found")

    if os.path.exists(target) and os.path.isfile(target):
        return FileResponse(target)

    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not Found")
