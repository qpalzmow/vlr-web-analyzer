import time
import threading
from app.config import CACHE_TTLS

CACHE = {
    key: {'data': {}, 'ttl': ttl}
    for key, ttl in CACHE_TTLS.items()
}

_cache_lock = threading.RLock()
_cache_timestamps = {}
_cache_gc_timer = None

def make_cache_key(entity_id, event_ids=None):
    """Build a clean, deterministic cache key for an entity and optional event_ids list."""
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

# Start background GC loop on module import
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

def get_cached_live_score(match_url, fetch_func):
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
        data = fetch_func(match_url)
    except Exception:
        data = {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    
    with _cache_lock:
        LIVE_SCORE_CACHE[match_url] = (now, data)
        
    return data
