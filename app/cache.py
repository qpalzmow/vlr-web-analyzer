"""Short-lived live scores with request coalescing and access-driven cleanup."""
import time
import threading
from concurrent.futures import Future

_cache_lock = threading.RLock()

LIVE_SCORE_CACHE = {}
CACHE_TTL = 20
CACHE_GC_INTERVAL = 60
_last_gc_ts = 0.0

_live_score_in_flight: dict[str, Future] = {}

def get_cached_live_score(match_url, fetch_func):
    global _last_gc_ts
    now = time.monotonic()
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

        if match_url in _live_score_in_flight:
            future = _live_score_in_flight[match_url]
            is_leader = False
        else:
            future = Future()
            _live_score_in_flight[match_url] = future
            is_leader = True

    if not is_leader:
        try:
            return future.result(timeout=15.0)
        except Exception:
            return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}

    try:
        data = fetch_func(match_url)
        with _cache_lock:
            LIVE_SCORE_CACHE[match_url] = (time.monotonic(), data)
        future.set_result(data)
        return data
    except Exception:
        data = {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
        future.set_result(data)
        return data
    finally:
        with _cache_lock:
            _live_score_in_flight.pop(match_url, None)
