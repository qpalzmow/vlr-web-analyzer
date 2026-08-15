import time
import logging
import threading
from app.cache import get_cached_data, CACHE, _cache_lock, _cache_timestamps, make_cache_key
from app.scraper.vlr import (
    get_matches, get_match_details, get_event_map_pool,
    get_team_events, get_team_form, get_team_maps_stats,
    get_team_roster, get_player_stats, get_team_advanced_metrics
)

logger = logging.getLogger(__name__)

_warmer_thread = None
_stop_warmer = False

MAJOR_REGIONS = {"Pacific", "EMEA", "Americas", "China", "Global"}

def is_major_match(m: dict) -> bool:
    """Check if match belongs to 4 major leagues or Masters/Champions (S-Tier)."""
    tier_s = m.get("tier") == "S-Tier"
    region_match = m.get("region") in MAJOR_REGIONS
    return tier_s or region_match

def is_completed_match(m: dict) -> bool:
    """Check if match is already completed/finished."""
    status = (m.get("status") or "").lower()
    return "final" in status or "ago" in status or "completed" in status

def warm_match_data(match_item: dict):
    """Pre-cache all details, rosters, maps, and player stats for a major match."""
    match_url = match_item.get("url")
    if not match_url:
        return
    
    try:
        # 1. Match details
        details = get_cached_data('match_details', match_url, get_match_details, match_url)
        team_a_id = details.get("team_a_id")
        team_b_id = details.get("team_b_id")
        event_id = details.get("event_id")
        
        # 2. Events & Map pool
        if event_id:
            get_cached_data('event_map_pool', event_id, get_event_map_pool, event_id)
        if team_a_id:
            get_cached_data('team_events', team_a_id, get_team_events, team_a_id)
        if team_b_id:
            get_cached_data('team_events', team_b_id, get_team_events, team_b_id)
            
        # 3. Team Form
        if team_a_id:
            get_cached_data('team_form', team_a_id, get_team_form, team_a_id)
        if team_b_id:
            get_cached_data('team_form', team_b_id, get_team_form, team_b_id)
            
        # 4. Maps stats
        key_a_all = make_cache_key(team_a_id, None)
        key_b_all = make_cache_key(team_b_id, None)
        if team_a_id:
            get_cached_data('team_stats', key_a_all, get_team_maps_stats, team_a_id, None)
        if team_b_id:
            get_cached_data('team_stats', key_b_all, get_team_maps_stats, team_b_id, None)
            
        # 5. Rosters & Player stats
        roster_a = get_cached_data('team_roster', team_a_id, get_team_roster, team_a_id) if team_a_id else []
        roster_b = get_cached_data('team_roster', team_b_id, get_team_roster, team_b_id) if team_b_id else []
        
        for p in roster_a:
            if p.get('id'):
                pkey = make_cache_key(p['id'], None)
                get_cached_data('player_stats', pkey, get_player_stats, p['id'], None)
        for p in roster_b:
            if p.get('id'):
                pkey = make_cache_key(p['id'], None)
                get_cached_data('player_stats', pkey, get_player_stats, p['id'], None)
                
        # 6. Advanced metrics
        if team_a_id:
            get_cached_data('pistol_stats', key_a_all, get_team_advanced_metrics, team_a_id, None)
        if team_b_id:
            get_cached_data('pistol_stats', key_b_all, get_team_advanced_metrics, team_b_id, None)
            
        logger.info("Successfully pre-warmed cache for major match: %s vs %s", match_item.get("team_a"), match_item.get("team_b"))
    except Exception as e:
        logger.warning("Failed to pre-warm cache for %s: %s", match_url, e)

def evict_old_matches_cache(completed_urls: set):
    """Evict completed/past match details and transient caches."""
    if not completed_urls:
        return
    with _cache_lock:
        if 'match_details' in CACHE:
            for url in completed_urls:
                CACHE['match_details']['data'].pop(url, None)
                _cache_timestamps.get('match_details', {}).pop(url, None)
        logger.info("Evicted %d completed matches from cache", len(completed_urls))

def warm_cache_cycle():
    """Main worker cycle: Warm major league upcoming matches and evict old matches."""
    try:
        matches = get_cached_data('matches', 'matches_list', get_matches)
        major_upcoming = []
        completed_urls = set()
        
        for m in matches:
            if is_major_match(m):
                if is_completed_match(m):
                    completed_urls.add(m.get("url"))
                else:
                    major_upcoming.append(m)
            elif is_completed_match(m):
                completed_urls.add(m.get("url"))
                
        # 1. Evict completed matches from detailed cache
        if completed_urls:
            evict_old_matches_cache(completed_urls)
            
        # 2. Pre-warm top major upcoming/live matches (limit to top 8 to prevent excessive rate)
        logger.info("Pre-warming %d major upcoming/live matches...", len(major_upcoming[:8]))
        for m in major_upcoming[:8]:
            if _stop_warmer:
                break
            warm_match_data(m)
            time.sleep(0.5) # Gentle pacing to protect VLR from rate limits
            
    except Exception as e:
        logger.warning("Error in warm_cache_cycle: %s", e)

def _warmer_worker_loop():
    logger.info("Major League Cache Warmer daemon started.")
    # Run initial warm cycle after short delay
    time.sleep(2)
    while not _stop_warmer:
        warm_cache_cycle()
        # Sleep for 5 minutes (300 seconds) between cycles
        for _ in range(300):
            if _stop_warmer:
                break
            time.sleep(1)

def start_cache_warmer():
    global _warmer_thread, _stop_warmer
    _stop_warmer = False
    if _warmer_thread is None or not _warmer_thread.is_alive():
        _warmer_thread = threading.Thread(target=_warmer_worker_loop, daemon=True, name="CacheWarmer")
        _warmer_thread.start()

def stop_cache_warmer():
    global _stop_warmer
    _stop_warmer = True
