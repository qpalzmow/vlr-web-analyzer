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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.config import PORT, PUBLIC_DIR, PUBLIC_DIR_NORM
from app.schemas import (
    TeamAnalysisPayload, FullAnalysisPayload, BanPickPayload, MatchDetailsResponse,
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

from app.db import (
    init_db, get_cached_team_data, save_team_data,
    get_sync_status, get_cached_matches, save_matches_cache,
    get_cached_match_details, save_cached_match_details,
    get_all_cached_match_details_map, get_cached_team_events_map
)
from app.catalog import (start_catalog_scheduler, stop_catalog_scheduler, refresh_catalog,
                         read_catalog, read_selection)
from app.analysis import bootstrap_analysis, full_analysis, AnalysisNotReady

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
    bootstrap_analysis()
    start_catalog_scheduler()
    yield
    stop_catalog_scheduler()
    _global_executor.shutdown(wait=True)
    close_httpx_client()

app = FastAPI(
    title="VLR Web Analyzer API",
    version="3.2.0",
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
_maintenance_last_started = None
MAINTENANCE_INTERVAL_SECONDS = 300


def _authorize_maintenance(request: Request):
    token = os.environ.get("VLR_MAINTENANCE_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="Manual maintenance is disabled")
    provided = request.headers.get("authorization", "")
    if not secrets.compare_digest(provided.encode(), f"Bearer {token}".encode()):
        raise HTTPException(status_code=401, detail="Maintenance authentication required")


def _submit_maintenance(request: Request, job, *args):
    global _maintenance_last_started
    _authorize_maintenance(request)
    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Maintenance task already running or queued")
    try:
        now = time.monotonic()
        if (_maintenance_last_started is not None
                and now - _maintenance_last_started < MAINTENANCE_INTERVAL_SECONDS):
            raise HTTPException(status_code=429, detail="Wait five minutes between maintenance requests")
        future = _global_executor.submit(job, *args)
        _maintenance_last_started = now
    except BaseException:
        _maintenance_lock.release()
        raise
    future.add_done_callback(lambda _: _maintenance_lock.release())

@app.get("/api/catalog")
def api_get_catalog():
    return JSONResponse(content=read_catalog(), headers={"Cache-Control": "no-store"})


@app.get("/api/matches")
def api_get_matches():
    return JSONResponse(content=read_catalog()["matches"], headers={"Cache-Control": "no-store"})


@app.get("/api/match-details")
def api_get_match_details(url: str = Query(...), include_map_pool: bool = True):
    # Compatibility endpoint for existing clients; never triggers a scrape.
    try:
        selection = read_selection(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not selection:
        raise HTTPException(status_code=409, detail="Match is awaiting the next hourly update")
    return JSONResponse(content=selection)


@app.get("/api/match-map-pool")
def api_get_match_map_pool(url: str = Query(...)):
    try:
        selection = read_selection(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not selection:
        raise HTTPException(status_code=409, detail="Match is awaiting the next hourly update")
    return {"map_pool": selection.get("map_pool", [])}


@app.get("/api/live-score")
def api_get_live_score(url: str = Query(...)):
    try:
        clean_url = validate_vlr_url(url)
        if not read_selection(clean_url):
            raise HTTPException(status_code=409, detail='Match is awaiting the next hourly update')
        clean_url = 'https://www.vlr.gg/' + urlparse(clean_url).path.strip('/').split('/')[0]
        live_score = get_cached_live_score(clean_url, get_live_score)
        return JSONResponse(content=live_score)
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("api_get_live_score failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analyze")
def api_full_analysis(payload: FullAnalysisPayload):
    try:
        data = full_analysis(payload.team_a_id, payload.team_b_id, payload.event_ids, payload.map_pool)
        return JSONResponse(content=data, headers={"Cache-Control": "no-store"})
    except AnalysisNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def prepared_sections(payload, section):
    from app.analysis import aggregate_team
    from app.db import get_analysis_teams
    records = get_analysis_teams([payload.team_a_id, payload.team_b_id])
    data = {}
    empty = {'scopes': {'all': {'maps': {}, 'players': {}, 'collected_at': None}},
             'available_events': [], 'updated_at': None}
    for side, tid in (('a', payload.team_a_id), ('b', payload.team_b_id)):
        if tid and not records.get(tid, {}).get('scopes'):
            raise HTTPException(status_code=409, detail='Analysis is awaiting collection')
        try:
            team = aggregate_team(records.get(tid, empty), payload.event_ids)
        except AnalysisNotReady as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        data[f'{section}_{side}'] = team['advanced' if section == 'adv' else section]
    return JSONResponse(content=data, headers={'Cache-Control': 'no-store'})


@app.post('/api/analyze/form')
def api_analyze_form(payload: TeamAnalysisPayload):
    return prepared_sections(payload, 'form')


@app.post('/api/analyze/maps')
def api_analyze_maps(payload: TeamAnalysisPayload):
    return prepared_sections(payload, 'maps')


@app.post('/api/analyze/aces')
def api_analyze_aces(payload: TeamAnalysisPayload):
    return prepared_sections(payload, 'ace')


@app.post('/api/analyze/advanced')
def api_analyze_advanced(payload: TeamAnalysisPayload):
    return prepared_sections(payload, 'adv')

@app.get("/api/sync/status")
def api_get_sync_status_endpoint():
    from app.analysis import analysis_status
    return JSONResponse(content={**get_sync_status(), 'analytics': analysis_status()})

@app.post("/api/sync/trigger")
def api_trigger_sync_endpoint(request: Request):
    _submit_maintenance(request, refresh_catalog)
    return JSONResponse(content={"status": "sync_triggered"})

@app.post("/api/simulate/banpick")
def api_simulate_banpick(payload: BanPickPayload):
    try:
        maps = payload.model_dump()
        res = simulate_banpick(maps['maps_a'], maps['maps_b'], payload.map_pool)
        return JSONResponse(content=res)
    except Exception as e:
        logger.error("api_simulate_banpick failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/cache/warm")
def api_trigger_cache_warm(request: Request):
    _submit_maintenance(request, refresh_catalog)
    return JSONResponse(content={"status": "warming_triggered"})

@app.post("/api/log-error")
async def api_log_error(request: Request):
    try:
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 10240:
                return JSONResponse(content={"status": "rejected", "reason": "payload too large"}, status_code=413)
            raw.extend(chunk)
        try:
            body = json.loads(raw)
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
        return FileResponse(target, headers={"Cache-Control": "no-cache"})

    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="Not Found")
