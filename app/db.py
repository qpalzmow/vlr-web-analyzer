import os
import json
import sqlite3
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "vlr_analyzer.db")


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with row_factory and WAL mode enabled."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for high concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    """Initializes the database schema if tables do not exist."""
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS team_data (
                    team_id TEXT PRIMARY KEY,
                    team_name TEXT,
                    maps_json TEXT,
                    form_json TEXT,
                    ace_json TEXT,
                    advanced_json TEXT,
                    events_json TEXT,
                    updated_at TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS matches_cache (
                    cache_key TEXT PRIMARY KEY,
                    matches_json TEXT,
                    updated_at TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS match_details_cache (
                    match_url TEXT PRIMARY KEY,
                    details_json TEXT,
                    map_pool_json TEXT,
                    team_a_events_json TEXT,
                    team_b_events_json TEXT,
                    updated_at TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    last_synced_at TEXT,
                    status TEXT,
                    details_json TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_team_updated ON team_data(updated_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_match_details_updated ON match_details_cache(updated_at);")
        logger.info("SQLite database initialized at %s", DB_PATH)
    finally:
        conn.close()


def save_team_data(
    team_id: str,
    team_name: str = "",
    maps_data: Optional[Dict[str, Any]] = None,
    form_data: Optional[List[str]] = None,
    ace_data: Optional[Dict[str, Any]] = None,
    advanced_data: Optional[Dict[str, Any]] = None,
    events_data: Optional[List[Dict[str, Any]]] = None
):
    """Saves or updates a team's analytics record atomically using COALESCE."""
    if not team_id:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    maps_json = json.dumps(maps_data, ensure_ascii=False) if maps_data is not None else None
    form_json = json.dumps(form_data, ensure_ascii=False) if form_data is not None else None
    ace_json = json.dumps(ace_data, ensure_ascii=False) if ace_data is not None else None
    adv_json = json.dumps(advanced_data, ensure_ascii=False) if advanced_data is not None else None
    ev_json = json.dumps(events_data, ensure_ascii=False) if events_data is not None else None

    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO team_data (team_id, team_name, maps_json, form_json, ace_json, advanced_json, events_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(team_id) DO UPDATE SET
                    team_name = CASE WHEN excluded.team_name <> '' THEN excluded.team_name ELSE team_data.team_name END,
                    maps_json = COALESCE(excluded.maps_json, team_data.maps_json),
                    form_json = COALESCE(excluded.form_json, team_data.form_json),
                    ace_json = COALESCE(excluded.ace_json, team_data.ace_json),
                    advanced_json = COALESCE(excluded.advanced_json, team_data.advanced_json),
                    events_json = COALESCE(excluded.events_json, team_data.events_json),
                    updated_at = excluded.updated_at;
            """, (str(team_id), team_name or "", maps_json, form_json, ace_json, adv_json, ev_json, now_iso))
    finally:
        conn.close()


def get_cached_team_data(team_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves cached analytics for a team. Returns None if not found."""
    if not team_id:
        return None
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM team_data WHERE team_id = ?", (str(team_id),))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "team_id": row["team_id"],
            "team_name": row["team_name"],
            "maps": json.loads(row["maps_json"] or "{}"),
            "form": json.loads(row["form_json"] or "[]"),
            "ace": json.loads(row["ace_json"] or "{}"),
            "advanced": json.loads(row["advanced_json"] or "{}"),
            "events": json.loads(row["events_json"] or "[]"),
            "updated_at": row["updated_at"]
        }
    except Exception as e:
        logger.warning("Error fetching cached team data for %s: %s", team_id, e)
        return None
    finally:
        conn.close()


def save_matches_cache(tier: str, region: str, matches: List[Dict[str, Any]]):
    """Saves matches list for tier and region."""
    cache_key = f"{tier}:{region}"
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO matches_cache (cache_key, matches_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    matches_json = excluded.matches_json,
                    updated_at = excluded.updated_at;
            """, (cache_key, json.dumps(matches, ensure_ascii=False), now_iso))
    finally:
        conn.close()


def get_cached_matches(tier: str, region: str, max_age_seconds: int = 600) -> Optional[List[Dict[str, Any]]]:
    """Retrieves cached matches list for tier and region with TTL verification."""
    cache_key = f"{tier}:{region}"
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT matches_json, updated_at FROM matches_cache WHERE cache_key = ?", (cache_key,))
        row = cursor.fetchone()
        if not row or not row["matches_json"]:
            return None
        if row["updated_at"]:
            try:
                updated_at = datetime.fromisoformat(row["updated_at"])
                age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                if age > max_age_seconds:
                    return None
            except Exception:
                pass
        return json.loads(row["matches_json"])
    except Exception as e:
        logger.warning("Error reading cached matches for %s: %s", cache_key, e)
        return None
    finally:
        conn.close()


def save_cached_match_details(
    match_url: str,
    details: Dict[str, Any],
    map_pool: Optional[List[str]] = None,
    team_a_events: Optional[List[Dict[str, Any]]] = None,
    team_b_events: Optional[List[Dict[str, Any]]] = None
):
    """Saves or updates cached match details and map pool in SQLite."""
    if not match_url or not details:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO match_details_cache (match_url, details_json, map_pool_json, team_a_events_json, team_b_events_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_url) DO UPDATE SET
                    details_json = excluded.details_json,
                    map_pool_json = COALESCE(excluded.map_pool_json, match_details_cache.map_pool_json),
                    team_a_events_json = COALESCE(excluded.team_a_events_json, match_details_cache.team_a_events_json),
                    team_b_events_json = COALESCE(excluded.team_b_events_json, match_details_cache.team_b_events_json),
                    updated_at = excluded.updated_at;
            """, (
                match_url,
                json.dumps(details, ensure_ascii=False),
                json.dumps(map_pool or [], ensure_ascii=False),
                json.dumps(team_a_events or [], ensure_ascii=False),
                json.dumps(team_b_events or [], ensure_ascii=False),
                now_iso
            ))
    except Exception as e:
        logger.warning("Error saving cached match details for %s: %s", match_url, e)
    finally:
        conn.close()


def get_cached_match_details(match_url: str, max_age_seconds: int = 3600) -> Optional[Dict[str, Any]]:
    """Retrieves cached match details from SQLite with TTL check."""
    if not match_url:
        return None
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM match_details_cache WHERE match_url = ?", (match_url,))
        row = cursor.fetchone()
        if not row:
            m_id = re.search(r'/(\d+)', match_url)
            if m_id:
                mid = m_id.group(1)
                cursor = conn.execute(
                    "SELECT * FROM match_details_cache WHERE match_url LIKE ? OR match_url LIKE ? LIMIT 1",
                    (f"%/{mid}/%", f"%/{mid}")
                )
                row = cursor.fetchone()
        if not row or not row["details_json"]:
            return None
        if row["updated_at"]:
            try:
                updated_at = datetime.fromisoformat(row["updated_at"])
                age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                if age > max_age_seconds:
                    return None
            except Exception:
                pass
        return {
            "details": json.loads(row["details_json"]),
            "map_pool": json.loads(row["map_pool_json"] or "[]"),
            "team_a_events": json.loads(row["team_a_events_json"] or "[]"),
            "team_b_events": json.loads(row["team_b_events_json"] or "[]"),
            "updated_at": row["updated_at"]
        }
    except Exception as e:
        logger.warning("Error reading cached match details for %s: %s", match_url, e)
        return None
    finally:
        conn.close()


def get_all_cached_match_details_map() -> Dict[str, Dict[str, Any]]:
    """Returns all cached match details mapped by match_url and match_id in a single ultra-fast query."""
    conn = get_db_connection()
    res = {}
    try:
        cursor = conn.execute("SELECT match_url, details_json FROM match_details_cache")
        for row in cursor.fetchall():
            try:
                det = json.loads(row["details_json"])
                u = row["match_url"]
                res[u] = det
                m_id = re.search(r'/(\d+)', u)
                if m_id:
                    res[m_id.group(1)] = det
            except Exception:
                pass
        return res
    except Exception as e:
        logger.warning("Error getting all cached match details map: %s", e)
        return {}
    finally:
        conn.close()


def set_sync_status(status: str, details: Optional[Dict[str, Any]] = None):
    """Updates global daily sync status metadata."""
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("""
                INSERT INTO sync_meta (key, last_synced_at, status, details_json)
                VALUES ('daily_sync', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    last_synced_at = excluded.last_synced_at,
                    status = excluded.status,
                    details_json = excluded.details_json;
            """, (now_iso, status, json.dumps(details or {}, ensure_ascii=False)))
    finally:
        conn.close()


def get_sync_status() -> Dict[str, Any]:
    """Returns the last daily sync status."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM sync_meta WHERE key = 'daily_sync'")
        row = cursor.fetchone()
        
        # Count total synced teams
        cursor_teams = conn.execute("SELECT COUNT(*) as cnt FROM team_data")
        team_count = cursor_teams.fetchone()["cnt"]

        if not row:
            return {
                "last_synced_at": None,
                "status": "not_started",
                "synced_teams_count": team_count,
                "details": {}
            }
        return {
            "last_synced_at": row["last_synced_at"],
            "status": row["status"],
            "synced_teams_count": team_count,
            "details": json.loads(row["details_json"] or "{}")
        }
    except Exception as e:
        logger.warning("Error getting sync status: %s", e)
        return {"status": "error", "error": str(e), "synced_teams_count": 0}
    finally:
        conn.close()
