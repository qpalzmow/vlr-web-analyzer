import os
import sys
import json
import traceback
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
from app.cache import get_cached_data, get_cached_live_score, make_cache_key
from app.scraper.http import close_httpx_client, request_with_retry, validate_vlr_url
from app.scraper.vlr import (
    get_matches, get_match_details, get_event_map_pool,
    get_team_events, get_live_score, get_team_form,
    get_team_maps_stats, get_team_roster, get_player_stats,
    get_team_advanced_metrics
)
from app.scraper.metrics import find_ace_player_from_stats, simulate_banpick

from app.cache_warmer import start_cache_warmer, stop_cache_warmer, warm_cache_cycle

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

_global_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vlr-api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_cache_warmer()
    yield
    stop_cache_warmer()
    _global_executor.shutdown(wait=True)
    close_httpx_client()

app = FastAPI(
    title="VLR Web Analyzer API",
    version="2.0.0",
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
            stats["name"] = p.get("name", "N/A")
            return stats
        except Exception:
            return None

    players_data = [get_stats_for_player(p) for p in roster]
    valid_players = [p for p in players_data if p is not None]
    return find_ace_player_from_stats(valid_players)

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

@app.get("/api/matches")
def api_get_matches():
    try:
        matches = get_cached_data('matches', 'matches_list', get_matches)
        return JSONResponse(content=matches)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/match-details")
def api_get_match_details(url: str = Query(...)):
    try:
        validate_vlr_url(url)
        details = get_cached_data('match_details', url, get_match_details, url)

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
        live_score = get_cached_live_score(url, get_live_score)

        return JSONResponse(content={
            "details": details,
            "team_a_events": team_a_events,
            "team_b_events": team_b_events,
            "map_pool": map_pool,
            "live_score": live_score
        })
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/live-score")
def api_get_live_score(url: str = Query(...)):
    try:
        validate_vlr_url(url)
        live_score = get_cached_live_score(url, get_live_score)
        return JSONResponse(content=live_score)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/form")
def api_analyze_form(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(
            get_cached_data, 'team_form', payload.team_a_id, get_team_form, payload.team_a_id
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_form', payload.team_b_id, get_team_form, payload.team_b_id
        ) if payload.team_b_id else None

        return JSONResponse(content={
            "form_a": _safe_future_result(future_a, []),
            "form_b": _safe_future_result(future_b, [])
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/maps")
def api_analyze_maps(payload: TeamAnalysisPayload):
    try:
        key_a = make_cache_key(payload.team_a_id, payload.event_ids)
        key_b = make_cache_key(payload.team_b_id, payload.event_ids)

        future_a = _global_executor.submit(
            get_cached_data, 'team_stats', key_a, get_team_maps_stats, payload.team_a_id, payload.event_ids
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_stats', key_b, get_team_maps_stats, payload.team_b_id, payload.event_ids
        ) if payload.team_b_id else None

        return JSONResponse(content={
            "maps_a": _safe_future_result(future_a, {}),
            "maps_b": _safe_future_result(future_b, {})
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/aces")
def api_analyze_aces(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(
            get_cached_data, 'team_roster', payload.team_a_id, get_team_roster, payload.team_a_id
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_roster', payload.team_b_id, get_team_roster, payload.team_b_id
        ) if payload.team_b_id else None

        roster_a = _safe_future_result(future_a, [])
        roster_b = _safe_future_result(future_b, [])

        ace_a = find_ace_player(roster_a, payload.event_ids)
        ace_b = find_ace_player(roster_b, payload.event_ids)

        return JSONResponse(content={"ace_a": ace_a, "ace_b": ace_b})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/advanced")
def api_analyze_advanced(payload: TeamAnalysisPayload):
    try:
        key_a = make_cache_key(payload.team_a_id, payload.event_ids)
        key_b = make_cache_key(payload.team_b_id, payload.event_ids)

        future_a = _global_executor.submit(
            get_cached_data, 'pistol_stats', key_a, get_team_advanced_metrics, payload.team_a_id, payload.event_ids
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'pistol_stats', key_b, get_team_advanced_metrics, payload.team_b_id, payload.event_ids
        ) if payload.team_b_id else None

        default_adv = get_team_advanced_metrics("")
        return JSONResponse(content={
            "adv_a": _safe_future_result(future_a, default_adv),
            "adv_b": _safe_future_result(future_b, default_adv)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/simulate/banpick")
def api_simulate_banpick(payload: BanPickPayload):
    try:
        res = simulate_banpick(payload.maps_a, payload.maps_b, payload.map_pool)
        return JSONResponse(content=res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cache/warm")
def api_trigger_cache_warm():
    try:
        _global_executor.submit(warm_cache_cycle)
        return JSONResponse(content={"status": "warming_triggered"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        # Sanitize: only log known fields
        safe_fields = {k: str(v)[:500] for k, v in body.items() if k in ('message', 'source', 'lineno', 'colno', 'stack')}
        print(f"\n>>> [BROWSER ERROR LOGGED]:\n{json.dumps(safe_fields, indent=2)}\n")
        return JSONResponse(content={"status": "logged"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{file_path:path}")
def serve_static(file_path: str):
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
