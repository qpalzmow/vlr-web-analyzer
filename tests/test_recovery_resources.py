import sys
import time
import os
import subprocess
from threading import Lock
from types import SimpleNamespace

import pytest
from app import catalog, recovery_worker


def test_recovery_child_never_raises_existing_memory_limit(monkeypatch):
    calls = []
    fake = SimpleNamespace(RLIMIT_AS=9, RLIM_INFINITY=-1,
                           getrlimit=lambda _: (200 * 1024 * 1024, -1),
                           setrlimit=lambda key, limits: calls.append((key, limits)))
    monkeypatch.setitem(sys.modules, 'resource', fake)
    recovery_worker.limit_memory()
    assert calls == [(9, (200 * 1024 * 1024, 200 * 1024 * 1024))]
    fake.getrlimit = lambda _: (-1, -1)
    recovery_worker.limit_memory()
    assert calls[-1] == (9, (320 * 1024 * 1024, 320 * 1024 * 1024))


def test_single_worker_recovery_really_bounds_inflight_catalog_parsing(monkeypatch):
    monkeypatch.setenv('VLR_COLLECTION_WORKERS', '1')
    lock, active, maximum = Lock(), 0, 0
    def fetch(key):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(.01)
        with lock:
            active -= 1
        return key
    failures = []
    assert catalog._collect(range(6), fetch, failures, 'team') == {i: i for i in range(6)}
    assert maximum == 1 and failures == []


@pytest.mark.skipif(os.name == 'nt', reason='Production address-space limit uses Linux resource')
def test_real_child_memory_exhaustion_does_not_escape_its_limit():
    code = ('from app.recovery_worker import limit_memory; limit_memory()\n'
            'try:\n    bytearray(1024 * 1024 * 1024)\n'
            'except MemoryError:\n    print("limited")\n'
            'else:\n    raise SystemExit("memory limit was not applied")\n')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'limited'
