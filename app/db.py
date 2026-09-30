import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

DB_DIR = os.environ.get("VLR_DATA_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
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
            # Serialize additive migrations across server workers.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS catalog_snapshot (
                    id INTEGER PRIMARY KEY CHECK (id = 1), payload_json TEXT NOT NULL
                );
            """)
            conn.execute("CREATE TABLE IF NOT EXISTS analysis_teams (team_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS analysis_sources (source_key TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    last_synced_at TEXT,
                    status TEXT,
                    details_json TEXT
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_lease (
                    key TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL
                )
            """)
        logger.info("SQLite database initialized at %s", DB_PATH)
    finally:
        conn.close()


def get_catalog_snapshot():
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT payload_json FROM catalog_snapshot WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def install_prepared_snapshot(catalog, teams):
    """Install one public generation atomically, without rolling newer data back."""
    def stamp(value):
        return datetime.fromisoformat(value)

    conn = get_db_connection()
    updated = 0
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload_json FROM catalog_snapshot WHERE id = 1").fetchone()
            previous = json.loads(row[0]) if row else None
            catalog_changed = not previous or stamp(catalog['updated_at']) > stamp(previous['updated_at'])
            if catalog_changed:
                conn.execute("INSERT INTO catalog_snapshot VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json",
                             (json.dumps(catalog, ensure_ascii=False),))
            for tid, payload in teams.items():
                row = conn.execute("SELECT payload_json FROM analysis_teams WHERE team_id = ?", (tid,)).fetchone()
                old = json.loads(row[0]) if row else {}
                incoming = payload.get('last_attempt_at') or payload['updated_at']
                incoming_date = stamp(incoming)
                prior = old.get('last_attempt_at') or old.get('updated_at')
                if prior and old.get('schema_version') == payload['schema_version'] and stamp(prior) >= incoming_date:
                    continue
                conn.execute("INSERT INTO analysis_teams VALUES (?, ?) ON CONFLICT(team_id) DO UPDATE SET payload_json=excluded.payload_json",
                             (tid, json.dumps(payload, ensure_ascii=False)))
                updated += 1
        return {'catalog_changed': catalog_changed, 'updated_teams': updated}
    finally:
        conn.close()


def save_catalog_snapshot(payload):
    # Readers see either the entire previous generation or the entire new one.
    encoded = json.dumps(payload, ensure_ascii=False)
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("INSERT INTO catalog_snapshot (id, payload_json) VALUES (1, ?) "
                         "ON CONFLICT(id) DO UPDATE SET payload_json = excluded.payload_json", (encoded,))
    finally:
        conn.close()


def get_analysis_teams(team_ids=None):
    conn = get_db_connection()
    try:
        if team_ids is None:
            rows = conn.execute("SELECT team_id, payload_json FROM analysis_teams").fetchall()
        else:
            ids = list(dict.fromkeys(str(t) for t in team_ids))
            if not ids:
                return {}
            rows = conn.execute("SELECT team_id, payload_json FROM analysis_teams WHERE team_id IN (" +
                                ','.join('?' for _ in ids) + ')', ids).fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}
    finally:
        conn.close()


def save_analysis_team(team_id, payload):
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("INSERT INTO analysis_teams VALUES (?, ?) ON CONFLICT(team_id) DO UPDATE SET payload_json=excluded.payload_json",
                         (str(team_id), json.dumps(payload, ensure_ascii=False)))
    finally:
        conn.close()


def save_analysis_seed(teams):
    """Insert missing seed teams together; collected records always take priority."""
    rows = [(str(tid), json.dumps(payload, ensure_ascii=False)) for tid, payload in teams.items()]
    conn = get_db_connection()
    try:
        with conn:
            conn.executemany("INSERT OR IGNORE INTO analysis_teams VALUES (?, ?)", rows)
    finally:
        conn.close()


def get_analysis_metadata(team_ids=None):
    """Read freshness and availability without materializing player/map payloads."""
    conn = get_db_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM analysis_teams").fetchone()[0]
        query = """SELECT team_id,
            CASE WHEN json_type(payload_json, '$.last_success_at') IS NULL
                 THEN json_extract(payload_json, '$.updated_at')
                 ELSE json_extract(payload_json, '$.last_success_at') END AS last_success_at,
            json_extract(payload_json, '$.last_error') AS last_error,
            COALESCE(json_type(payload_json, '$.scopes') = 'object'
                     AND length(json_extract(payload_json, '$.scopes')) > 2, 0) AS has_scopes
            FROM analysis_teams"""
        ids = list(dict.fromkeys(str(tid) for tid in team_ids)) if team_ids is not None else None
        if ids == []:
            return {}, count
        if ids is not None:
            query += " WHERE team_id IN (" + ','.join('?' for _ in ids) + ')'
        rows = conn.execute(query, ids or []).fetchall()
        return {row['team_id']: dict(row) for row in rows}, count
    finally:
        conn.close()


def get_analysis_source(key, max_age_seconds=3600, not_before=None):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT updated_at,payload_json FROM analysis_sources WHERE source_key=?", (key,)).fetchone()
        if (row and (not_before is None or datetime.fromisoformat(row[0]) >= not_before)
                and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(row[0])).total_seconds() < max_age_seconds):
            return json.loads(row[1])
        return None
    finally:
        conn.close()


def save_analysis_source(key, payload):
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("INSERT INTO analysis_sources VALUES (?, ?, ?) ON CONFLICT(source_key) DO UPDATE SET updated_at=excluded.updated_at,payload_json=excluded.payload_json",
                         (key, datetime.now(timezone.utc).isoformat(), json.dumps(payload, ensure_ascii=False)))
    finally:
        conn.close()


def set_sync_status(status: str, details: Optional[Dict[str, Any]] = None):
    """Updates hourly collection status metadata."""
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
    """Returns the last collection status."""
    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM sync_meta WHERE key = 'daily_sync'")
        row = cursor.fetchone()
        
        # Count total synced teams
        cursor_teams = conn.execute("SELECT COUNT(*) as cnt FROM analysis_teams")
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
