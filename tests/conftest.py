import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
import app.db as db_module

@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Automatically redirects all DB operations during tests to an isolated temp sqlite file."""
    test_db_path = str(tmp_path / "test_vlr.db")
    monkeypatch.setattr(db_module, "DB_PATH", test_db_path)
    monkeypatch.setattr(db_module, "DB_DIR", str(tmp_path))
    db_module.init_db()
    yield test_db_path


@pytest.fixture(autouse=True)
def isolate_memory_state(monkeypatch):
    import app.main as main
    from app.cache import CACHE, LIVE_SCORE_CACHE, _cache_lock, _cache_timestamps
    monkeypatch.delenv("VLR_MAINTENANCE_TOKEN", raising=False)
    monkeypatch.setattr(main, "_maintenance_last_started", None)
    with _cache_lock:
        for config in CACHE.values():
            config["data"].clear()
        LIVE_SCORE_CACHE.clear()
        _cache_timestamps.clear()

@pytest.fixture
def client():
    return TestClient(app)
