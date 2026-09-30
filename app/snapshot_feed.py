"""Import public data collected independently of a sleeping web service."""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.db import install_prepared_snapshot

FEED_URL = 'https://raw.githubusercontent.com/qpalzmow/vlr-web-analyzer/catalog-data/snapshot.json'
MAX_BYTES = 16 * 1024 * 1024


def enabled():
    return os.environ.get('VLR_REFRESH_MODE', 'snapshot' if os.environ.get('RENDER') == 'true' else 'local') == 'snapshot'


def timestamp(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None or date > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Invalid snapshot timestamp')
    return date


def validate(payload):
    from app.catalog import SCHEMA_VERSION as catalog_schema
    from app.analysis import SCHEMA_VERSION as analysis_schema
    if payload.get('schema_version') != 1:
        raise ValueError('Unsupported public snapshot')
    timestamp(payload['published_at'])
    catalog, analysis = payload['catalog'], payload['analysis']
    if catalog.get('schema_version') != catalog_schema or analysis.get('schema_version') != analysis_schema:
        raise ValueError('Incompatible data schema')
    timestamp(catalog['updated_at'])
    matches, teams = catalog['matches'], analysis['teams']
    if not catalog.get('generation') or not matches or not isinstance(teams, dict):
        raise ValueError('Empty public snapshot')
    if catalog.get('ready_count') != sum(m.get('selection_status') == 'ready' for m in matches):
        raise ValueError('Invalid selection count')
    if not catalog['ready_count'] or not teams:
        raise ValueError('Public snapshot has no prepared data')
    for match in matches:
        if not str(match['id']).isdigit():
            raise ValueError('Invalid match ID')
        if match.get('selection_status') == 'ready':
            selection = match['selection_data']
            for side in ('a', 'b'):
                if not str(selection['details'][f'team_{side}_id']).isdigit() or not isinstance(selection[f'team_{side}_events'], list):
                    raise ValueError('Invalid selection')
    for tid, team in teams.items():
        if not tid.isdigit():
            raise ValueError('Invalid team ID')
        # Failed first attempts may contain no statistics; never import these as ready teams.
        if not team.get('scopes'):
            continue
        if team.get('schema_version') != analysis_schema:
            raise ValueError('Incompatible team schema')
        timestamp(team['updated_at'])
        if team.get('last_attempt_at'):
            timestamp(team['last_attempt_at'])
        for scope in team['scopes'].values():
            timestamp(scope['collected_at'])
            if not isinstance(scope.get('maps'), dict) or not isinstance(scope.get('players'), dict):
                raise ValueError('Invalid analysis scope')
    return payload


def install(payload):
    validate(payload)
    teams = {tid: team for tid, team in payload['analysis']['teams'].items() if team.get('scopes')}
    return install_prepared_snapshot(payload['catalog'], teams)


def download():
    # Fixed public repository, no bearer token, no user-provided URL or redirects.
    with httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False) as client:
        with client.stream('GET', FEED_URL, params={'v': int(time.time() // 300)},
                           headers={'Cache-Control': 'no-cache'}) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError('Public snapshot exceeds size limit')
    return validate(json.loads(body))


def refresh():
    payload = download()
    installed = install(payload)
    return {**installed, 'published_at': payload['published_at'],
            'catalog_updated_at': payload['catalog']['updated_at']}
