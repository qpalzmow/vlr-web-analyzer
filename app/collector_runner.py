"""Bound collector subprocesses; thread cancellation is not an I/O time limit."""
import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


JOB_SECONDS = 55 * 60
PUBLISH_RESERVE = 180
COLLECTOR_GRACE = 60
STAGE_LIMITS = {'recover': 30, 'catalog': 660, 'analysis': 2460, 'finalize': 30}


@dataclass(frozen=True)
class Budget:
    cooperative: float
    hard: float
    grace: float


def plan_budget(stage, deadline, *, now=None):
    """Charge setup and earlier stages against one job clock, reserving publication."""
    now = time.monotonic() if now is None else now
    # Finalization is part of the reserved publication work, not another collector.
    reserve = 120 if stage == 'finalize' else PUBLISH_RESERVE
    remaining = deadline - now - reserve
    hard = min(STAGE_LIMITS[stage], max(0, remaining))
    grace = COLLECTOR_GRACE if stage in ('catalog', 'analysis') else 2
    if hard <= grace:
        return None
    return Budget(cooperative=hard - grace, hard=hard, grace=grace)


def _signal_group(process, *, force):
    if os.name == 'nt':
        # Windows has no POSIX TERM group signal. Reclaim the tree while its
        # parent is still alive, rather than losing descendants after terminate().
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False, timeout=2)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass


def supervise(command, *, hard_seconds, grace_seconds=60, env=None, stop_event=None):
    """Return the child's exit code, 124 on timeout, or 130 after shutdown cancellation.

    TERM starts before the absolute hard limit. Its grace period is included in
    that limit; a blocked HTTP response cannot extend it by another full grace.
    """
    if not (math.isfinite(hard_seconds) and 0 < grace_seconds < hard_seconds):
        raise ValueError('The hard limit must exceed a positive termination grace')
    if stop_event is not None and stop_event.is_set():
        return 130
    started = time.monotonic()
    reap_margin = min(2, grace_seconds / 4)
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    process = subprocess.Popen(command, env=env, **options)
    def wait_until(deadline):
        if stop_event is None:
            return process.wait(timeout=max(0, deadline - time.monotonic()))
        while True:
            if stop_event.is_set():
                _signal_group(process, force=True)
                process.wait(timeout=2)
                return 130
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, hard_seconds)
            try:
                return process.wait(timeout=min(.25, remaining))
            except subprocess.TimeoutExpired:
                pass
    try:
        try:
            return wait_until(started + hard_seconds - grace_seconds)
        except subprocess.TimeoutExpired:
            _signal_group(process, force=False)
        try:
            result = wait_until(started + hard_seconds - reap_margin)
            if result == 130:
                return 130
        except subprocess.TimeoutExpired:
            _signal_group(process, force=True)
            process.wait(timeout=max(reap_margin, started + hard_seconds - time.monotonic()))
        # Kill remaining descendants even when the root exited on TERM.
        if os.name != 'nt':
            _signal_group(process, force=True)
        return 124
    except BaseException:
        _signal_group(process, force=True)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        raise


def validate_publishable(payload):
    """Publication accepts validated, settled stage results, including old files."""
    from app.snapshot_feed import validate
    payload = validate(payload)
    collection = dict(payload.get('collection', {}))
    if 'catalog' not in collection and payload['catalog'].get('collection') is not None:
        collection['catalog'] = payload['catalog']['collection']
    if collection.get('status') not in (None, 'completed', 'partial', 'catalog_only', 'retained_previous', 'failed'):
        raise ValueError('Cannot publish an unfinished collection')
    generation = payload['catalog']['generation']
    for stage in ('catalog', 'analysis'):
        result = collection.get(stage)
        if result is None:
            continue  # Public snapshots without stage metadata remain compatible.
        allowed = {'completed', 'partial', 'retained_previous', 'failed'}
        if stage == 'analysis':
            allowed.add('skipped')
            if collection.get('mode') == 'catalog_only' or collection.get('status') == 'catalog_only':
                allowed.add('pending')
        if not isinstance(result, dict) or result.get('status') not in allowed:
            raise ValueError(f'Cannot publish an unfinished {stage} result')
        if not result.get('completed_at'):
            raise ValueError(f'Cannot publish an unfinished {stage} attempt')
        if result.get('catalog_generation') != generation:
            raise ValueError(f'{stage} result belongs to another catalog generation')
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=tuple(STAGE_LIMITS))
    parser.add_argument('--interrupted-stage', choices=('catalog', 'analysis'))
    parser.add_argument('--exit-code', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--validate-publish', type=Path)
    args = parser.parse_args(argv)
    if args.validate_publish:
        validate_publishable(json.loads(args.validate_publish.read_text(encoding='utf-8')))
        return 0
    if not args.stage or not args.output:
        parser.error('--stage and --output are required when supervising collection')
    if args.stage == 'finalize' and (args.interrupted_stage is None or args.exit_code is None):
        parser.error('--interrupted-stage and --exit-code are required for finalization')
    try:
        deadline = float(os.environ['COLLECTOR_JOB_DEADLINE'])
    except (KeyError, ValueError):
        parser.error('COLLECTOR_JOB_DEADLINE must be set at the start of the job')
    if not math.isfinite(deadline):
        parser.error('COLLECTOR_JOB_DEADLINE must be finite')
    budget = plan_budget(args.stage, deadline)
    if budget is None:
        print(f'::warning::No {args.stage} budget remains after reserving publication time.', flush=True)
        return 124
    command = [sys.executable, '-m', 'app.snapshot_export', '--output', str(args.output)]
    if args.previous:
        command.extend(['--previous', str(args.previous)])
    if args.stage == 'recover':
        command.append('--recover-only')
    elif args.stage == 'finalize':
        command.extend(['--finalize-interrupted', '--stage', args.interrupted_stage,
                        '--exit-code', str(args.exit_code)])
    elif args.stage == 'catalog':
        command.extend(['--catalog-only', '--catalog-max-seconds', str(budget.cooperative)])
    else:
        command.extend(['--analysis-only', '--max-seconds', str(budget.cooperative)])
    print(f'{args.stage}: cooperative={budget.cooperative:.1f}s; hard={budget.hard:.1f}s '
          f'(includes {budget.grace:.1f}s termination grace).', flush=True)
    return supervise(command, hard_seconds=budget.hard, grace_seconds=budget.grace)


if __name__ == '__main__':
    raise SystemExit(main())
