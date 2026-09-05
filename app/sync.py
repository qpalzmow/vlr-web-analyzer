import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Set, Tuple

from app.db import (
    init_db, save_team_data, save_matches_cache,
    set_sync_status, get_sync_status, get_cached_team_data,
    save_cached_match_details, get_cached_match_details
)
from app.scraper.vlr import (
    get_matches, get_team_events, get_team_maps_stats,
    get_team_form, get_team_roster, get_player_stats,
    get_team_advanced_metrics, get_match_details,
    get_event_map_pool
)
from app.scraper.metrics import find_ace_player_from_stats
from app.config import CORE_S_TIER_TEAMS

logger = logging.getLogger(__name__)

# Global lock to prevent overlapping sync runs
_sync_lock = threading.Lock()
_sync_thread = None


def sync_single_team(team_id: str, team_name: str = "") -> bool:
    """Scrapes and compiles complete analytics for a single team, writing directly to SQLite."""
    if not team_id:
        return False
    try:
        # 1. Events list (top 3 events used as default active scope)
        events = get_team_events(team_id)
        default_event_ids = [e["id"] for e in events[:3]] if events else None

        # 2. Form (Recent matches)
        form = get_team_form(team_id, max_results=10)

        # 3. Maps stats
        maps_data = get_team_maps_stats(team_id, default_event_ids)

        # 4. Roster & Player Stats & Ace Player
        roster = get_team_roster(team_id)
        players_stats = []
        if roster:
            with ThreadPoolExecutor(max_workers=5) as p_exec:
                futures = {p_exec.submit(get_player_stats, p["id"], default_event_ids): p for p in roster}
                for f in as_completed(futures):
                    p_info = futures[f]
                    try:
                        pdata = f.result()
                        pdata["name"] = p_info["name"]
                        players_stats.append(pdata)
                    except Exception as pe:
                        logger.warning("Error fetching stats for player %s in team %s: %s", p_info["name"], team_id, pe)

        ace_data = find_ace_player_from_stats(players_stats) if players_stats else {
            "nickname": "N/A", "acs": 0.0, "kd_margin": 0, "agents": ["N/A"]
        }

        # 5. Advanced Metrics (FK/FD & Map WR)
        adv_data = get_team_advanced_metrics(team_id, default_event_ids)

        # Save atomically to SQLite
        save_team_data(
            team_id=team_id,
            team_name=team_name,
            maps_data=maps_data,
            form_data=form,
            ace_data=ace_data,
            advanced_data=adv_data,
            events_data=events
        )
        logger.info("Successfully synced team: %s (%s)", team_name or team_id, team_id)
        return True
    except Exception as e:
        logger.warning("Failed to sync team %s (%s): %s", team_name, team_id, e)
        return False


def run_daily_sync(force: bool = False) -> Dict[str, Any]:
    """Runs the full daily sync across all 4 major leagues."""
    global _sync_lock
    if not _sync_lock.acquire(blocking=False):
        logger.info("Daily sync already running. Skipping duplicate trigger.")
        return {"status": "already_running"}

    try:
        set_sync_status("running", {"started_at": datetime.now(timezone.utc).isoformat()})
        logger.info(">>> [DAILY SYNC STARTED]: Syncing 4 Major League tournaments and team profiles...")
        init_db()

        # 1. Collect matches for all major leagues
        regions = ["pacific", "americas", "emea", "china", "all"]
        discovered_teams: Dict[str, str] = CORE_S_TIER_TEAMS.copy()  # Pre-seed with all core VCT partner teams
        total_matches = 0
        failures: List[Dict[str, str]] = []

        try:
            all_matches = get_matches()
        except Exception as e:
            logger.error("Failed to fetch matches catalog: %s", e)
            all_matches = []
            failures.append({"step": "get_matches", "error": str(e)})

        # Save region caches in SQLite
        for reg in regions:
            try:
                if reg == "all":
                    matches = all_matches
                else:
                    matches = [
                        m for m in all_matches
                        if m.get("region", "").lower() == reg.lower()
                    ]
                save_matches_cache(tier="s_tier", region=reg, matches=matches)
                total_matches += len(matches)
            except Exception as me:
                logger.warning("Failed to save matches cache for region %s: %s", reg, me)
                failures.append({"region": reg, "error": str(me)})

        # 2. Extract unique matches and pre-cache details in parallel
        unique_matches_map: Dict[str, Dict[str, Any]] = {}
        for m in all_matches:
            m_url = m.get("url") or m.get("match_url")
            if m_url and m_url not in unique_matches_map:
                unique_matches_map[m_url] = m

        def process_match_details(m_url: str, m_info: Dict[str, Any]):
            try:
                # Check DB cache first to avoid re-scraping
                cached = get_cached_match_details(m_url, max_age_seconds=86400)
                if cached and cached.get("details"):
                    det = cached["details"]
                    return (
                        det.get("team_a_id"),
                        det.get("team_a_name", m_info.get("team_a", "")),
                        det.get("team_b_id"),
                        det.get("team_b_name", m_info.get("team_b", ""))
                    )

                details = get_match_details(m_url)
                if details:
                    event_id = details.get("event_id")
                    map_pool = get_event_map_pool(event_id) if event_id else []
                    ta_id = details.get("team_a_id")
                    tb_id = details.get("team_b_id")
                    ev_a = get_team_events(ta_id) if ta_id else []
                    ev_b = get_team_events(tb_id) if tb_id else []
                    save_cached_match_details(
                        match_url=m_url,
                        details=details,
                        map_pool=map_pool,
                        team_a_events=ev_a,
                        team_b_events=ev_b
                    )
                    return (
                        details.get("team_a_id"),
                        details.get("team_a_name", m_info.get("team_a", "")),
                        details.get("team_b_id"),
                        details.get("team_b_name", m_info.get("team_b", ""))
                    )
            except Exception:
                pass
            return None, None, None, None

        # Pre-cache details for matches with up to 6 workers
        with ThreadPoolExecutor(max_workers=6) as m_exec:
            match_futures = [
                m_exec.submit(process_match_details, u, info)
                for u, info in unique_matches_map.items()
            ]
            for f in as_completed(match_futures):
                try:
                    ta_id, ta_name, tb_id, tb_name = f.result()
                    if ta_id:
                        discovered_teams[str(ta_id)] = ta_name
                    if tb_id:
                        discovered_teams[str(tb_id)] = tb_name
                except Exception:
                    pass

        logger.info("Discovered %d unique teams across %d matches.", len(discovered_teams), total_matches)

        # 3. Sync all discovered teams in parallel (max 4 workers to stay polite to VLR)
        synced_count = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(sync_single_team, tid, tname)
                for tid, tname in discovered_teams.items()
            ]
            for f in as_completed(futures):
                if f.result():
                    synced_count += 1

        details = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "total_matches_indexed": total_matches,
            "total_teams_discovered": len(discovered_teams),
            "teams_synced_successfully": synced_count
        }
        if failures:
            details["failures"] = failures
            status = "degraded" if synced_count > 0 else "error"
        else:
            status = "completed"

        set_sync_status(status, details)
        logger.info(">>> [HOURLY S-TIER SYNC %s]: %d teams synced into SQLite DB.", status.upper(), synced_count)
        return {"status": status, "details": details}
    except Exception as e:
        logger.error("Hourly S-Tier sync encountered an error: %s", e, exc_info=True)
        set_sync_status("error", {"error": str(e), "failed_at": datetime.now(timezone.utc).isoformat()})
        return {"status": "error", "error": str(e)}
    finally:
        _sync_lock.release()


def _daily_scheduler_loop():
    """Background daemon loop that triggers S-Tier sync hourly (every 1 hour)."""
    logger.info("Hourly S-Tier sync background scheduler started.")
    time.sleep(25)  # Let server boot and serve incoming HTTP traffic first
    while True:
        try:
            status = get_sync_status()
            last_synced = status.get("last_synced_at")
            needs_sync = False

            if not last_synced:
                needs_sync = True
            else:
                try:
                    last_dt = datetime.fromisoformat(last_synced)
                    # Run if more than 1 hour (3600s) has passed
                    if datetime.now(timezone.utc) - last_dt > timedelta(hours=1):
                        needs_sync = True
                except Exception:
                    needs_sync = True

            if needs_sync and status.get("status") != "running":
                logger.info("1 hour elapsed since last sync. Triggering automatic hourly S-Tier sync.")
                run_daily_sync()

        except Exception as e:
            logger.warning("Error in hourly sync scheduler loop: %s", e)

        # Check every 5 minutes (300 seconds)
        time.sleep(300)


def start_sync_scheduler():
    """Starts the hourly S-Tier sync background thread."""
    global _sync_thread
    if _sync_thread is None or not _sync_thread.is_alive():
        _sync_thread = threading.Thread(target=_daily_scheduler_loop, daemon=True, name="VLRHourlySyncScheduler")
        _sync_thread.start()
        logger.info("Hourly S-Tier sync background worker thread spawned.")
