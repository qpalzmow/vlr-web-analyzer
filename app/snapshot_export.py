"""Hourly GitHub runner: collect using the same parsers and publish public counts."""
import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.analysis import SCHEMA_VERSION, bootstrap_analysis, refresh_analysis
from app.catalog import bootstrap_snapshot, build_snapshot
from app.db import init_db, get_catalog_snapshot, save_catalog_snapshot, get_analysis_teams
from app.snapshot_feed import install, validate


def write_snapshot(path):
    payload = {'schema_version': 1, 'published_at': datetime.now(timezone.utc).isoformat(),
               'catalog': get_catalog_snapshot(),
               'analysis': {'schema_version': SCHEMA_VERSION, 'teams': get_analysis_teams()}}
    validate(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    init_db()
    bootstrap_snapshot()
    bootstrap_analysis()
    if args.previous and args.previous.exists():
        install(json.loads(args.previous.read_text(encoding='utf-8')))
    payload = build_snapshot(get_catalog_snapshot())
    save_catalog_snapshot(payload)
    # Preserve a publishable catalog even if the runner reaches its time budget
    # during analysis. Each completed team updates this file atomically.
    write_snapshot(args.output)
    result = refresh_analysis(payload['matches'], force=True,
                              on_progress=lambda _: write_snapshot(args.output))
    write_snapshot(args.output)
    logging.info('Catalog: %s; analysis: %s', payload['updated_at'], result)


if __name__ == '__main__':
    main()
