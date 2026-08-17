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
    db_module.init_db()
    yield test_db_path

@pytest.fixture
def client():
    return TestClient(app)
