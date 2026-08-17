import time
import logging
import threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Set, Tuple

from app.db import (
    init_db, save_team_data, save_matches_cache,
    set_sync_status, get_sync_status, get_cached_team_data
)
from app.scraper.vlr import (
    get_matches, get_team_events, get_team_maps_stats,
    get_team_form, get_team_roster, get_player_stats,
    get_team_advanced_metrics, get_match_details
)
from app.scraper.metrics import find_ace_player_from_stats

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
        discovered_teams: Dict[str, str] = {}  # team_id -> team_name
        total_matches = 0

        for reg in regions:
            try:
                matches = get_matches(tier="s_tier", region=reg)
                save_matches_cache(tier="s_tier", region=reg, matches=matches)
                total_matches += len(matches)

                for m in matches:
                    if m.get("match_url"):
                        try:
                            # Quick details parse to extract team IDs if missing
                            details = get_match_details(m["match_url"])
                            if details.get("team_a_id"):
                                discovered_teams[str(details["team_a_id"])] = details.get("team_a_name", m.get("team_a", ""))
                            if details.get("team_b_id"):
                                discovered_teams[str(details["team_b_id"])] = details.get("team_b_name", m.get("team_b", ""))
                        except Exception:
                            pass
            except Exception as me:
                logger.warning("Failed to sync matches for region %s: %s", reg, me)

        logger.info("Discovered %d unique teams across %d matches.", len(discovered_teams), total_matches)

        # 2. Sync all discovered teams in parallel (max 6 workers to stay polite to VLR)
        synced_count = 0
        with ThreadPoolExecutor(max_workers=6) as executor:
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
        set_sync_status("completed", details)
        logger.info(">>> [DAILY SYNC COMPLETED]: %d teams synced into SQLite DB.", synced_count)
        return {"status": "completed", "details": details}
    except Exception as e:
        logger.error("Daily sync encountered an error: %s", e, exc_info=True)
        set_sync_status("error", {"error": str(e), "failed_at": datetime.now(timezone.utc).isoformat()})
        return {"status": "error", "error": str(e)}
    finally:
        _sync_lock.release()


def _daily_scheduler_loop():
    """Background daemon loop that triggers sync daily."""
    logger.info("Daily sync background scheduler started.")
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
                    # Run if more than 24 hours have passed
                    if datetime.now(timezone.utc) - last_dt > timedelta(hours=24):
                        needs_sync = True
                except Exception:
                    needs_sync = True

            if needs_sync and status.get("status") != "running":
                logger.info("24 hours elapsed since last sync. Triggering automatic daily sync.")
                run_daily_sync()

        except Exception as e:
            logger.warning("Error in daily sync scheduler loop: %s", e)

        # Check every 30 minutes
        time.sleep(1800)


def start_sync_scheduler():
    """Starts the daily sync background thread."""
    global _sync_thread
    if _sync_thread is None or not _sync_thread.is_alive():
        _sync_thread = threading.Thread(target=_daily_scheduler_loop, daemon=True, name="VLRDailySyncScheduler")
        _sync_thread.start()
        logger.info("Daily sync background worker thread spawned.")
