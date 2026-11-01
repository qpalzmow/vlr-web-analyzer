import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
from threading import Event, Thread
import time

import pytest

from app import collector_runner as runner


def public_payload():
    from app.analysis import SCHEMA_VERSION as analysis_schema
    from app.catalog import SCHEMA_VERSION as catalog_schema
    now = datetime.now(timezone.utc).isoformat()
    return {'schema_version': 1, 'published_at': now,
            'catalog': {'schema_version': catalog_schema, 'generation': 'verified', 'updated_at': now,
                        'ready_count': 1, 'matches': [
                            {'id': '1', 'selection_status': 'ready', 'selection_data': {
                                'details': {'match_id': '1', 'team_a_id': '1', 'team_b_id': '2'},
                                'team_a_events': [], 'team_b_events': []}}]},
            'analysis': {'schema_version': analysis_schema, 'teams': {
                '1': {'schema_version': analysis_schema, 'updated_at': now,
                      'scopes': {'all': {'collected_at': now, 'maps': {}, 'players': {}}}}}}}


def test_stage_budgets_include_termination_grace():
    assert runner.plan_budget('catalog', 3300, now=0) == runner.Budget(600, 660, 60)
    assert runner.plan_budget('analysis', 3300, now=0) == runner.Budget(2400, 2460, 60)


def test_install_time_and_catalog_publishing_reduce_analysis_not_publish_reserve():
    # 5 min setup, 11 min catalog, and 45 sec first publication have elapsed.
    budget = runner.plan_budget('analysis', 3300, now=300 + 660 + 45)
    assert budget == runner.Budget(2055, 2115, 60)
    assert 300 + 660 + 45 + budget.hard + runner.PUBLISH_RESERVE == 3300
    assert runner.plan_budget('catalog', 3300, now=3000) == runner.Budget(60, 120, 60)
    assert runner.plan_budget('analysis', 3300, now=3060) is None
    # Finalization consumes the publication reservation, leaving two minutes.
    assert runner.plan_budget('finalize', 3300, now=3120) == runner.Budget(28, 30, 2)


def test_supervisor_returns_unexpected_child_failure():
    assert runner.supervise([sys.executable, '-c', 'raise SystemExit(7)'],
                            hard_seconds=3, grace_seconds=.3) == 7


def test_supervisor_reclaims_term_ignoring_process_and_descendants(tmp_path):
    heartbeat = tmp_path / 'heartbeat'
    child = ("import signal, sys, time\nfrom pathlib import Path\n"
             "if hasattr(signal, 'SIGTERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
             "while True:\n Path(sys.argv[1]).write_text(str(time.monotonic()))\n time.sleep(.02)\n")
    parent = ("import signal, subprocess, sys, time\n"
              "if hasattr(signal, 'SIGTERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
              "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]])\n"
              "while True: time.sleep(.02)\n")
    started = time.monotonic()
    assert runner.supervise([sys.executable, '-c', parent, child, str(heartbeat)],
                            hard_seconds=1.5, grace_seconds=.4) == 124
    assert time.monotonic() - started < 3.5
    assert heartbeat.exists(), 'The child must actually start before the tree is reclaimed'
    stopped = heartbeat.read_text()
    time.sleep(.15)
    assert heartbeat.read_text() == stopped


def test_trickling_response_exceeds_read_timeout_but_process_limit_preserves_checkpoint(tmp_path):
    sent = Event()
    stop = Event()
    counts = []

    class Trickle(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '1000000')
            self.end_headers()
            try:
                while not stop.is_set():
                    self.wfile.write(b'x')
                    self.wfile.flush()
                    counts.append(1)
                    sent.set()
                    stop.wait(.025)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Trickle)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    checkpoint = tmp_path / 'collector-checkpoint.json'
    payload = public_payload()
    checkpoint.write_text(json.dumps(payload), encoding='utf-8')
    before = checkpoint.read_bytes()
    script = ('import httpx, sys\n'
              'httpx.get(sys.argv[1], timeout=httpx.Timeout(.15, connect=1), trust_env=False)\n'
              'raise RuntimeError("The streaming response must be interrupted by the supervisor")\n')
    # A Windows subprocess imports HTTPX afresh (including antivirus startup);
    # allow that setup while still proving the response exceeds its read timer.
    hard_limit = 6 if os.name == 'nt' else 2.5
    started = time.monotonic()
    try:
        code = runner.supervise([sys.executable, '-c', script, f'http://127.0.0.1:{server.server_port}/'],
                                 hard_seconds=hard_limit, grace_seconds=.4)
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert sent.is_set() and len(counts) >= 8, 'Exercise actual network reads beyond the .15s read timeout'
    assert code == 124 and elapsed < hard_limit + 2
    assert checkpoint.read_bytes() == before
    assert runner.validate_publishable(json.loads(checkpoint.read_text(encoding='utf-8'))) == payload


def test_publication_accepts_legacy_but_rejects_running_or_wrong_generation():
    payload = public_payload()
    assert runner.validate_publishable(payload) is payload
    for collection in ({'status': 'running'},
                       {'status': 'partial', 'catalog': {'status': 'running', 'catalog_generation': 'verified'}},
                       {'status': 'partial', 'catalog': {'status': 'partial', 'catalog_generation': 'other'}}):
        candidate = copy.deepcopy(payload)
        candidate['collection'] = collection
        with pytest.raises(ValueError):
            runner.validate_publishable(candidate)


def test_canonical_catalog_phase_without_top_metadata_must_be_settled():
    payload = public_payload()
    assert 'collection' not in payload and 'collection' not in payload['catalog']
    assert runner.validate_publishable(payload) is payload
    payload['catalog']['collection'] = {'status': 'retained_previous',
                                        'catalog_generation': payload['catalog']['generation'],
                                        'started_at': payload['catalog']['updated_at'], 'completed_at': None}
    with pytest.raises(ValueError, match='unfinished catalog attempt'):
        runner.validate_publishable(payload)
    payload['catalog']['collection']['completed_at'] = payload['catalog']['updated_at']
    assert runner.validate_publishable(payload) is payload
    payload['catalog']['collection']['status'] = 'running'
    with pytest.raises(ValueError):
        runner.validate_publishable(payload)


@pytest.mark.parametrize('catalog_status', ['completed', 'partial', 'retained_previous'])
def test_real_catalog_only_export_is_publishable_with_skipped_analysis(monkeypatch, tmp_path, catalog_status):
    """Exercise export, atomic checkpoint, DB write, then the workflow's gate."""
    from app import snapshot_export as export
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps(public_payload()), encoding='utf-8')
    output = tmp_path / 'snapshot.json'
    checkpoint = tmp_path / 'collector-checkpoint.json'

    def collect(prior, **kwargs):
        candidate = copy.deepcopy(prior)
        if catalog_status != 'retained_previous':
            candidate['generation'] = 'new-catalog'
            candidate['updated_at'] = datetime.now(timezone.utc).isoformat()
        phase = export.catalog_phase(candidate)
        phase.update(status=catalog_status, catalog_generation=candidate['generation'])
        candidate['collection'] = phase
        return candidate

    monkeypatch.setattr(export, 'build_snapshot', collect)
    monkeypatch.setattr(sys, 'argv', ['snapshot_export', '--catalog-only', '--previous', str(previous),
                                    '--output', str(output), '--checkpoint', str(checkpoint)])
    export.main()
    payload = json.loads(output.read_text(encoding='utf-8'))
    assert payload['collection']['catalog']['status'] == catalog_status
    assert payload['collection']['analysis']['status'] == 'skipped'
    assert runner.validate_publishable(payload) == payload
    assert json.loads(checkpoint.read_text(encoding='utf-8')) == payload
    pending = copy.deepcopy(payload)
    pending['collection']['analysis']['status'] = 'pending'
    assert runner.validate_publishable(pending) == pending
    invalid = copy.deepcopy(payload)
    invalid['collection']['analysis']['status'] = 'running'
    with pytest.raises(ValueError):
        runner.validate_publishable(invalid)
    invalid = copy.deepcopy(payload)
    invalid['collection']['catalog']['status'] = 'skipped'
    invalid['catalog']['collection']['status'] = 'skipped'
    with pytest.raises(ValueError):
        runner.validate_publishable(invalid)
    unfinished = copy.deepcopy(payload)
    unfinished['catalog']['collection'].update(status='retained_previous', completed_at=None)
    unfinished['collection']['catalog'] = copy.deepcopy(unfinished['catalog']['collection'])
    with pytest.raises(ValueError, match='unfinished catalog attempt'):
        runner.validate_publishable(unfinished)
    unfinished = copy.deepcopy(payload)
    unfinished['collection']['analysis']['completed_at'] = None
    with pytest.raises(ValueError, match='unfinished analysis attempt'):
        runner.validate_publishable(unfinished)


def test_runner_passes_matching_cooperative_budget_to_exporter(monkeypatch, tmp_path):
    monkeypatch.setenv('COLLECTOR_JOB_DEADLINE', '3300')
    monkeypatch.setattr(runner.time, 'monotonic', lambda: 1000)
    calls = []
    monkeypatch.setattr(runner, 'supervise', lambda command, **kw: calls.append((command, kw)) or 17)
    assert runner.main(['--stage', 'analysis', '--output', str(tmp_path / 'snapshot.json')]) == 17
    command, settings = calls[0]
    assert command[-3:] == ['--analysis-only', '--max-seconds', '2060.0']
    assert settings == {'hard_seconds': 2120.0, 'grace_seconds': 60}


def test_no_remaining_collection_budget_starts_no_child(monkeypatch, tmp_path):
    monkeypatch.setenv('COLLECTOR_JOB_DEADLINE', '3300')
    monkeypatch.setattr(runner.time, 'monotonic', lambda: 3120)
    monkeypatch.setattr(runner, 'supervise', lambda *args, **kw: pytest.fail('No budget for a process'))
    assert runner.main(['--stage', 'catalog', '--output', str(tmp_path / 'snapshot.json')]) == 124


def publisher_script():
    workflow = (Path(__file__).parents[1] / '.github/workflows/hourly-data.yml').read_text(encoding='utf-8')
    return textwrap.dedent(workflow.split("<<'BASH'\n", 1)[1].split('\n          BASH', 1)[0])


def bash_executable():
    bash = shutil.which('bash')
    if not bash and Path('C:/Program Files/Git/bin/bash.exe').exists():
        bash = 'C:/Program Files/Git/bin/bash.exe'
    if not bash or not shutil.which('git'):
        pytest.skip('The workflow publisher integration needs Git and Bash')
    return bash


def test_remote_push_failure_preserves_publication_then_checkpoint_can_publish(tmp_path):
    """Run the actual workflow publisher against a rejecting local Git remote."""
    bash = bash_executable()
    project = Path(__file__).parents[1]
    remote = tmp_path / 'public.git'
    first = tmp_path / 'first'
    published = first / 'published'
    published.mkdir(parents=True)

    def git(*args, cwd=project):
        return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout

    git('init', '--bare', remote)
    git('init', '-b', 'catalog-data', cwd=published)
    git('config', 'user.name', 'Test Collector', cwd=published)
    git('config', 'user.email', 'collector@example.test', cwd=published)
    prior = public_payload()
    (published / 'snapshot.json').write_text(json.dumps(prior), encoding='utf-8')
    git('add', 'snapshot.json', cwd=published)
    git('commit', '-m', 'Previous valid generation', cwd=published)
    git('remote', 'add', 'origin', remote, cwd=published)
    git('push', 'origin', 'HEAD:catalog-data', cwd=published)
    previous_head = git('--git-dir', remote, 'rev-parse', 'catalog-data').strip()
    checkpoint = tmp_path / 'collector-checkpoint.json'
    candidate = copy.deepcopy(prior)
    candidate['catalog']['generation'] = 'candidate'
    checkpoint.write_text(json.dumps(candidate), encoding='utf-8')
    baseline = checkpoint.read_bytes()
    script = tmp_path / 'publish.sh'
    script.write_text(publisher_script(), encoding='utf-8', newline='\n')
    hook = remote / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8', newline='\n')
    hook.chmod(hook.stat().st_mode | 0o111)

    def publish(run_directory):
        shutil.copyfile(checkpoint, run_directory / 'snapshot.json')
        env = dict(os.environ, RUNNER_TEMP=run_directory.as_posix(), GITHUB_WORKSPACE=project.as_posix(),
                   PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))
        return subprocess.run([bash, str(script)], cwd=project, env=env, timeout=15,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    failed = publish(first)
    assert failed.returncode != 0
    assert git('--git-dir', remote, 'rev-parse', 'catalog-data').strip() == previous_head
    assert checkpoint.read_bytes() == baseline
    runner.validate_publishable(json.loads(checkpoint.read_text(encoding='utf-8')))

    # A new workflow checks out the public branch afresh; it never trusts the
    # failed publisher's local commit or a cached database timestamp.
    hook.unlink()
    second = tmp_path / 'second'
    second.mkdir()
    git('clone', '--branch', 'catalog-data', remote, second / 'published')
    succeeded = publish(second)
    assert succeeded.returncode == 0, succeeded.stderr
    final = json.loads(git('--git-dir', remote, 'show', 'catalog-data:snapshot.json'))
    assert final['catalog']['generation'] == 'candidate'
