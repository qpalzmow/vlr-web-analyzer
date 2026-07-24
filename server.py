import os
import sys
import json
import time
import threading
import atexit
import traceback
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import scraper
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PORT = int(os.environ.get("PORT", 8000))

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PUBLIC_DIR = os.path.abspath(os.path.join(BASE_DIR, 'public'))
PUBLIC_DIR_NORM = os.path.normcase(os.path.normpath(PUBLIC_DIR))

# Comprehensive caching system with multiple TTL tiers
CACHE = {
    'matches': {'data': {}, 'ttl': 600},  # 10 minutes
    'match_details': {'data': {}, 'ttl': 300},  # 5 minutes
    'team_events': {'data': {}, 'ttl': 300},  # 5 minutes
    'event_map_pool': {'data': {}, 'ttl': 600},  # 10 minutes
    'live_score': {'data': {}, 'ttl': 10},  # 10 seconds
    'team_stats': {'data': {}, 'ttl': 600},  # 10 minutes
    'team_roster': {'data': {}, 'ttl': 600},  # 10 minutes
    'player_stats': {'data': {}, 'ttl': 300},  # 5 minutes
    'pistol_stats': {'data': {}, 'ttl': 300},  # 5 minutes
    'team_form': {'data': {}, 'ttl': 300},  # 5 minutes
}

_cache_lock = threading.RLock()
_cache_timestamps = {}
_global_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vlr-api")
atexit.register(_global_executor.shutdown, wait=True)

_cache_gc_timer = None

def _make_cache_key(entity_id, event_ids=None):
    if event_ids is None:
        return f"{entity_id}_all"
    if isinstance(event_ids, (list, set, tuple)):
        sorted_events = "_".join(sorted(str(e) for e in event_ids))
        return f"{entity_id}_{sorted_events}"
    return f"{entity_id}_{event_ids}"

def _cleanup_expired_cache_nolock(now: float):
    expired_keys = []
    for cache_type, cache_config in CACHE.items():
        if cache_type in _cache_timestamps:
            for key in list(cache_config['data'].keys()):
                if now - _cache_timestamps[cache_type].get(key, 0) > cache_config['ttl']:
                    expired_keys.append((cache_type, key))
    for cache_type, key in expired_keys:
        CACHE[cache_type]['data'].pop(key, None)
        _cache_timestamps.get(cache_type, {}).pop(key, None)

def _cache_gc_loop():
    global _cache_gc_timer
    _cleanup_expired_cache_nolock(time.time())
    _cache_gc_timer = threading.Timer(60.0, _cache_gc_loop)
    _cache_gc_timer.daemon = True
    _cache_gc_timer.start()

_cache_gc_loop()

def is_cache_valid(cache_type: str, key: str) -> bool:
    if cache_type not in CACHE or key not in CACHE[cache_type]['data']:
        return False
    ts_map = _cache_timestamps.get(cache_type)
    if not ts_map or key not in ts_map:
        return True
    return (time.time() - ts_map[key]) < CACHE[cache_type]['ttl']

def get_cached_data(cache_type: str, key: str, fetch_func, *args, **kwargs):
    if is_cache_valid(cache_type, key):
        return CACHE[cache_type]['data'][key]
    
    try:
        data = fetch_func(*args, **kwargs)
    except Exception as e:
        print(f"Error fetching {cache_type} for key {key}: {e}")
        raise
    
    with _cache_lock:
        CACHE[cache_type]['data'][key] = data
        if cache_type not in _cache_timestamps:
            _cache_timestamps[cache_type] = {}
        _cache_timestamps[cache_type][key] = time.time()
    return data

LIVE_SCORE_CACHE = {}
CACHE_TTL = 20
CACHE_GC_INTERVAL = 60
_last_gc_ts = 0.0

def get_cached_live_score(match_url):
    global _last_gc_ts
    now = time.time()
    with _cache_lock:
        if now - _last_gc_ts > CACHE_GC_INTERVAL:
            expired = [k for k, (ts, _) in LIVE_SCORE_CACHE.items() if now - ts > CACHE_GC_INTERVAL]
            for k in expired:
                del LIVE_SCORE_CACHE[k]
            _last_gc_ts = now
            
        if match_url in LIVE_SCORE_CACHE:
            ts, data = LIVE_SCORE_CACHE[match_url]
            if now - ts < CACHE_TTL:
                return data

    try:
        data = scraper.get_live_score(match_url)
    except Exception:
        data = {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    
    with _cache_lock:
        LIVE_SCORE_CACHE[match_url] = (now, data)
        
    return data

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
            player_cache_key = _make_cache_key(p['id'], event_ids)
            stats = get_cached_data('player_stats', player_cache_key, scraper.get_player_stats, p["id"], event_ids)
            rounds = stats["rounds"]
            acs = stats["weighted_acs"] / rounds if rounds > 0 else 0.0
            p_data = {
                "nickname": p["name"],
                "acs": acs,
                "kd_margin": stats["kills"] - stats["deaths"],
                "agents": sorted(stats["agents"].items(), key=lambda x: x[1], reverse=True)
            }
            def _cap(s):
                return s[0].upper() + s[1:] if s else s
            p_data["agents"] = [_cap(x[0]) for x in p_data["agents"][:3]]
            if not p_data["agents"]:
                p_data["agents"] = ["N/A"]
            return p_data
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        players_data = list(executor.map(get_stats_for_player, roster))
        
    valid_players = [p for p in players_data if p is not None]
    if not valid_players:
        return {"nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]}
        
    return max(valid_players, key=lambda x: x["acs"])

def simulate_banpick(maps_a, maps_b, map_pool):
    if not map_pool:
        return {"bans": [], "picks": []}
    
    def get_win_pct(maps_data, map_name):
        stats = maps_data.get(map_name, {})
        played = stats.get('played', 0)
        wins = stats.get('w', 0)
        return (wins / played * 100) if played > 0 else 50.0
    
    available = list(map_pool)
    bans = []
    picks = []
    
    for team_label, own_maps, opp_maps in [('Team A', maps_a, maps_b), ('Team B', maps_b, maps_a)]:
        if not available:
            break
        worst_map = None
        worst_diff = float('inf')
        for m in available:
            own_pct = get_win_pct(own_maps, m)
            opp_pct = get_win_pct(opp_maps, m)
            diff = own_pct - opp_pct
            if diff < worst_diff:
                worst_diff = diff
                worst_map = m
        if worst_map:
            bans.append({"map": worst_map, "team": team_label, "reason": f"Disadvantage: {worst_diff:+.1f}%"})
            available.remove(worst_map)
    
    for team_label, own_maps in [('Team A', maps_a), ('Team B', maps_b)]:
        if not available:
            break
        best_map = max(available, key=lambda m: get_win_pct(own_maps, m))
        pct = get_win_pct(own_maps, best_map)
        picks.append({"map": best_map, "team": team_label, "win_pct": round(pct, 1)})
        available.remove(best_map)
    
    if available:
        decider = available[0]
        picks.append({"map": decider, "team": "Decider", "win_pct": 50.0})
    
    return {"bans": bans, "picks": picks}

# --- FastAPI App Definition ---
app = FastAPI(title="VLR Web Analyzer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for request validation
class TeamAnalysisPayload(BaseModel):
    team_a_id: str = ""
    team_b_id: str = ""
    event_ids: Optional[List[str]] = None

class BanPickPayload(BaseModel):
    maps_a: Dict[str, Any] = {}
    maps_b: Dict[str, Any] = {}
    map_pool: List[str] = []

@app.get("/api/matches")
def api_get_matches():
    try:
        matches = get_cached_data('matches', 'matches_list', scraper.get_matches)
        return JSONResponse(content=matches)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/match-details")
def api_get_match_details(url: str = Query(...)):
    try:
        details = get_cached_data('match_details', url, scraper.get_match_details, url)
        future_a = _global_executor.submit(
            get_cached_data, 'team_events', details["team_a_id"], scraper.get_team_events, details["team_a_id"]
        ) if details.get("team_a_id") else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_events', details["team_b_id"], scraper.get_team_events, details["team_b_id"]
        ) if details.get("team_b_id") else None
        future_pool = _global_executor.submit(
            get_cached_data, 'event_map_pool', details.get("event_id"), scraper.get_event_map_pool, details.get("event_id")
        ) if details.get("event_id") else None
        
        team_a_events = _safe_future_result(future_a, [])[:12]
        team_b_events = _safe_future_result(future_b, [])[:12]
        map_pool = _safe_future_result(future_pool, [])
        live_score = get_cached_live_score(url)
        
        return JSONResponse(content={
            "details": details,
            "team_a_events": team_a_events,
            "team_b_events": team_b_events,
            "map_pool": map_pool,
            "live_score": live_score
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/live-score")
def api_get_live_score(url: str = Query(...)):
    try:
        live_score = get_cached_live_score(url)
        return JSONResponse(content=live_score)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze/form")
def api_analyze_form(payload: TeamAnalysisPayload):
    try:
        future_a = _global_executor.submit(
            get_cached_data, 'team_form', payload.team_a_id, scraper.get_team_form, payload.team_a_id
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_form', payload.team_b_id, scraper.get_team_form, payload.team_b_id
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
        key_a = _make_cache_key(payload.team_a_id, payload.event_ids)
        key_b = _make_cache_key(payload.team_b_id, payload.event_ids)
        
        future_a = _global_executor.submit(
            get_cached_data, 'team_stats', key_a, scraper.get_team_maps_stats, payload.team_a_id, payload.event_ids
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_stats', key_b, scraper.get_team_maps_stats, payload.team_b_id, payload.event_ids
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
            get_cached_data, 'team_roster', payload.team_a_id, scraper.get_team_roster, payload.team_a_id
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'team_roster', payload.team_b_id, scraper.get_team_roster, payload.team_b_id
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
        key_a = _make_cache_key(payload.team_a_id, payload.event_ids)
        key_b = _make_cache_key(payload.team_b_id, payload.event_ids)
        
        future_a = _global_executor.submit(
            get_cached_data, 'pistol_stats', key_a, scraper.get_team_advanced_metrics, payload.team_a_id, payload.event_ids
        ) if payload.team_a_id else None
        future_b = _global_executor.submit(
            get_cached_data, 'pistol_stats', key_b, scraper.get_team_advanced_metrics, payload.team_b_id, payload.event_ids
        ) if payload.team_b_id else None
        
        return JSONResponse(content={
            "adv_a": _safe_future_result(future_a, {"pistol_win_rate": 50.0, "fk_fd_margin": 0.0}),
            "adv_b": _safe_future_result(future_b, {"pistol_win_rate": 50.0, "fk_fd_margin": 0.0})
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

@app.post("/api/log-error")
async def api_log_error(request: Request):
    try:
        body = await request.json()
        print(f"\n>>> [BROWSER ERROR LOGGED]:\n{json.dumps(body, indent=2)}\n")
        return JSONResponse(content={"status": "logged"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files at root
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
    
    # Fallback to index.html for SPA routing
    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Not Found")

ACTUAL_PORT = PORT

def run(start_port=None):
    global ACTUAL_PORT
    target_port = start_port or PORT
    
    for attempt_port in range(target_port, target_port + 10):
        try:
            ACTUAL_PORT = attempt_port
            print(f"Starting FastAPI + Uvicorn server on port {ACTUAL_PORT}...")
            uvicorn.run(app, host="0.0.0.0", port=attempt_port)
            return
        except OSError as e:
            if attempt_port == target_port + 9:
                raise e
            continue


if __name__ == '__main__':
    run()