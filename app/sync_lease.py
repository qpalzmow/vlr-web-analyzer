"""A renewable SQLite lease prevents overlapping syncs across processes."""
import logging
import threading
import time
import uuid
from contextlib import contextmanager

from app.db import get_db_connection

logger = logging.getLogger(__name__)
LEASE_SECONDS = 300


def _claim(owner):
    conn = get_db_connection()
    try:
        with conn:
            now = time.time()
            return conn.execute("""
                INSERT INTO sync_lease (key, owner, expires_at)
                VALUES ('daily_sync', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    owner = excluded.owner, expires_at = excluded.expires_at
                WHERE sync_lease.expires_at <= ?
            """, (owner, now + LEASE_SECONDS, now)).rowcount == 1
    finally:
        conn.close()


def _renew(owner):
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("UPDATE sync_lease SET expires_at = ? WHERE owner = ?",
                         (time.time() + LEASE_SECONDS, owner))
    finally:
        conn.close()


@contextmanager
def sync_lease():
    owner = uuid.uuid4().hex
    if not _claim(owner):
        yield False
        return
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(60):
            try:
                _renew(owner)
            except Exception:
                logger.exception("Could not renew sync lease")

    worker = threading.Thread(target=heartbeat, daemon=True, name="VLRSyncLease")
    worker.start()
    try:
        yield True
    finally:
        stop.set()
        worker.join()
        conn = get_db_connection()
        try:
            with conn:
                conn.execute("DELETE FROM sync_lease WHERE owner = ?", (owner,))
        finally:
            conn.close()
