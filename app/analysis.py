"""Prepared per-event statistics; one read-only request produces the full report."""
import copy
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from app import analysis_sources as sources
from app.db import (get_analysis_teams, get_analysis_metadata, save_analysis_team,
                    save_analysis_seed, get_catalog_snapshot)
from app.scraper.metrics import (calculate_advanced_metrics, find_ace_player_from_stats, simulate_banpick,
                                 has_valid_acs, career_player_stats)
from app.scraper.http import CollectionBudgetExceeded
from app.config import collection_workers

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 3
MAP_FIELDS = ('played','w','l','atk_won','atk_total','def_won','def_total')


class AnalysisNotReady(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def expired(timestamp):
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds()
        return age < 0 or age >= 3600
    except (TypeError, ValueError):
        return True


def analysis_status(matches=None):
    if matches is None:
        matches = (get_catalog_snapshot() or {}).get('matches', [])
    active = requirements(matches)
    teams, stored_count = get_analysis_metadata(active if active else None)
    if active:
        teams = {tid: teams.get(tid, {}) for tid in active}
    return {'teams': len(teams), 'failed_teams': sum(bool(t.get('last_error')) for t in teams.values()),
            'stored_teams': stored_count, 'pending_teams': sum(not t.get('has_scopes') for t in teams.values()),
            'stale_teams': sum(expired(t.get('last_success_at')) for t in teams.values())}


def requirements(matches):
    teams = {}
    for match in matches:
        selection = match.get('selection_data')
        if not selection:
            continue
        # Include opponents' filters too, then use the team's complete participation
        # list to distinguish an unplayed event from a missing collection.
        events = {e['id'] for side in ('a','b') for e in selection.get(f'team_{side}_events', [])}
        for side in ('a','b'):
            tid = selection['details'].get(f'team_{side}_id')
            if tid:
                teams.setdefault(str(tid), set()).update(events)
    return teams


def own_event_requirements(matches):
    """Participation confirmed by a team's own menu, excluding its opponent's."""
    teams = {}
    for match in matches:
        selection = match.get('selection_data') or {}
        details = selection.get('details') or {}
        for side in ('a', 'b'):
            tid = details.get(f'team_{side}_id')
            if tid:
                teams.setdefault(str(tid), set()).update(
                    str(event['id']) for event in selection.get(f'team_{side}_events', []))
    return teams


def prepare_team(team_id, events, previous=None, *, force=False, known_events=None):
    previous = previous or {}
    confirmed = set(known_events or [])
    overview = (sources.team_overview(team_id, expected_events=confirmed) if confirmed
                else sources.team_overview(team_id))
    profile = sources.team_profile(team_id)
    # The validated catalog's own menu is also participation evidence. If the
    # overview lags behind it, collect the event scope instead of inventing zero.
    available = set(overview['available_events']) | confirmed
    required = set(events) & available
    old_scopes = previous.get('scopes', {})
    scopes = copy.deepcopy(old_scopes)
    failed = []
    budget_exhausted = False
    def needs_scope(key):
        return (force or previous.get('schema_version') != SCHEMA_VERSION
                or key in previous.get('failed_scopes', [])
                or expired(old_scopes.get(key, {}).get('collected_at')))

    career = old_scopes.get('all', {})
    roster_changed = (not career.get('career_roster_verified')
                      or set(career.get('players', {})) != set(profile['roster']))
    if needs_scope('all') or roster_changed:
        try:
            players = {pid: {**sources.player_totals(pid), 'name': name}
                       for pid, name in profile['roster'].items()}
            scopes['all'] = {'maps': overview['maps'], 'players': players, 'collected_at': now_iso(),
                             'career_roster_verified': True,
                             'acs_missing_players': sum(p['rounds'] > 0 and not has_valid_acs(p) for p in players.values()),
                             'acs_missing_rounds': sum(p.get('acs_missing_rounds', 0) for p in players.values()),
                             'players_available': any(p['rounds'] > 0 for p in players.values())}
        except Exception as exc:
            logger.exception('All-time player collection failed for %s', team_id)
            failed.append('all')
            budget_exhausted = isinstance(exc, CollectionBudgetExceeded)
    for event_id in sorted(required):
        if not needs_scope(event_id):
            continue
        if budget_exhausted:
            failed.append(event_id)
            continue
        try:
            maps = sources.event_maps(team_id, event_id)
            # An event leaderboard does not identify a player's team for each match.
            # Current roster membership cannot prove historical team coverage.
            scopes[event_id] = {'maps': maps, 'players': {}, 'players_available': False,
                                'collected_at': now_iso(), 'unavailable_reason': 'team_match_coverage_unverified'}
        except Exception as exc:
            logger.warning('Analysis event %s/%s: %s', team_id, event_id, exc)
            failed.append(event_id)
            budget_exhausted = isinstance(exc, CollectionBudgetExceeded)
    data = {'schema_version': SCHEMA_VERSION, 'team_id': team_id, 'team_name': profile['name'],
            'form': profile['form'], 'recent_matches': profile.get('recent_matches', []),
            'logo': profile.get('logo'), 'available_events': sorted(available), 'scopes': scopes,
            'updated_at': now_iso(), 'failed_scopes': failed,
            'budget_exhausted': budget_exhausted,
            'last_attempt_at': now_iso(), 'last_success_at': previous.get('last_success_at', previous.get('updated_at')) if failed else now_iso(),
            'last_error': 'scope_collection_failed' if failed else None}
    save_analysis_team(team_id, data)
    logger.info('Prepared analysis team %s: %d event scopes, %d failures', team_id, len(scopes)-('all' in scopes), len(failed))
    return data


def refresh_analysis(matches, stop=None, force=False, on_progress=None):
    sources.refresh_started_at = datetime.now(timezone.utc) if force else None
    previous = get_analysis_teams()
    own_events = own_event_requirements(matches)
    todo = []
    for tid, events in requirements(matches).items():
        old = previous.get(tid, {})
        required = (set(events) & set(old.get('available_events', []))) | own_events.get(tid, set()) | {'all'}
        scopes = old.get('scopes', {})
        fresh = all(not expired(scopes.get(key, {}).get('collected_at')) for key in required)
        if (force or not fresh or own_events.get(tid, set()) - set(old.get('available_events', []))
                or old.get('schema_version') != SCHEMA_VERSION
                or old.get('last_error') or old.get('failed_scopes')):
            todo.append((tid, events))
    results = {'updated': 0, 'failed': 0, 'total': len(todo)}
    # A time-limited external run must not repeatedly refresh the same first teams
    # while leaving the end of the queue untouched.
    todo.sort(key=lambda item: previous.get(item[0], {}).get('last_success_at') or
              previous.get(item[0], {}).get('updated_at') or '')
    workers = collection_workers()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='vlr-prepared-analysis') as pool:
        # Bounded batches make shutdown responsive without queueing thousands of requests.
        for i in range(0, len(todo), workers):
            if results.get('budget_exhausted') or (stop and stop.is_set()):
                break
            jobs = {pool.submit(prepare_team, tid, events, previous.get(tid), force=force,
                                **({'known_events': own_events[tid]} if own_events.get(tid) else {})): tid
                    for tid, events in todo[i:i+workers]}
            for future in as_completed(jobs):
                try:
                    prepared = future.result()
                    if prepared.get('budget_exhausted'):
                        results['budget_exhausted'] = True
                        if stop is not None:
                            stop.set()
                    # A returned record can still contain failed scopes and older data.
                    results['failed' if prepared.get('last_error') or prepared.get('budget_exhausted') else 'updated'] += 1
                except Exception as exc:
                    results['failed'] += 1
                    budget_exhausted = isinstance(exc, CollectionBudgetExceeded)
                    if budget_exhausted:
                        results['budget_exhausted'] = True
                        if stop is not None:
                            stop.set()
                    tid = jobs[future]
                    old = copy.deepcopy(previous.get(tid, {}))
                    if own_events.get(tid):
                        old['available_events'] = sorted(set(old.get('available_events', [])) | own_events[tid])
                    old.update(last_attempt_at=now_iso(), last_error='team_collection_failed',
                               budget_exhausted=budget_exhausted)
                    save_analysis_team(tid, old)
                    logger.warning('Keeping previous analysis for team %s: %s', jobs[future], exc)
                if on_progress:
                    on_progress(results.copy())
    return results


def bootstrap_analysis():
    seed = Path(__file__).resolve().parents[1] / 'data' / 'analysis_seed.json'
    if not seed.exists():
        return
    try:
        data = json.loads(seed.read_text(encoding='utf-8'))
        if data.get('schema_version') != SCHEMA_VERSION:
            return
        save_analysis_seed(data.get('teams', {}))
    except Exception:
        logger.exception('Could not load analysis seed')


def career_comparison(data):
    """Select a current player's career independently of the team's map filters.

    The verified scope contains every roster member, including explicitly empty
    player pages. A failed fetch never publishes a partial replacement scope.
    """
    scope = data.get('scopes', {}).get('all', {})
    verified = scope.get('career_roster_verified', False)
    players = scope.get('players', {}) if verified else {}
    recorded = [{**player, 'player_id': pid} for pid, player in players.items()
                if player.get('rounds', 0) > 0]
    missing = [player.get('name', pid) for pid, player in players.items()
               if player.get('rounds', 0) <= 0]
    missing_acs = [player for player in recorded if not has_valid_acs(player)]
    ace = find_ace_player_from_stats(recorded)
    reason = None
    if not scope:
        reason = 'career_not_ready'
    elif not verified:
        reason = 'roster_unverified'
    elif not players:
        reason = 'no_roster'
    elif not recorded:
        reason = 'no_player_stats'
    elif not ace['acs_available']:
        reason = 'source_acs_missing'
    return {**ace, 'scope': 'career', 'available': ace['acs_available'],
            'acs_unavailable_reason': reason if not ace['acs_available'] else None,
            'partial': bool(recorded) and bool(missing or missing_acs),
            'roster_size': len(players), 'players_with_stats': len(recorded),
            'players_with_acs': len(recorded) - len(missing_acs),
            'players_missing_acs': [player.get('name', player['player_id']) for player in missing_acs],
            'acs_missing_rounds': sum(player.get('acs_missing_rounds', 0) for player in recorded),
            'missing_players': missing, 'unavailable_reason': reason,
            'collected_at': scope.get('collected_at')}


def aggregate_team(data, event_ids=None):
    scopes = data.get('scopes', {})
    if not event_ids:
        keys = ['all']
    else:
        # A known nonparticipant contributes zero, never its all-time statistics.
        keys = sorted(set(event_ids) & set(data['available_events']))
    missing = [key for key in keys if key not in scopes]
    if missing:
        raise AnalysisNotReady('선택한 대회의 통계를 준비 중입니다. 다음 업데이트 후 다시 선택해주세요.')
    maps, dates = {}, []
    for key in keys:
        item = scopes[key]
        dates.append(item['collected_at'])
        for name, counts in item.get('maps', {}).items():
            target = maps.setdefault(name, {field: 0 for field in MAP_FIELDS})
            for field in MAP_FIELDS:
                target[field] += counts.get(field, 0)
    advanced = calculate_advanced_metrics(maps, 0, 0, 0)
    # Never divide career/event-player totals by the team's unrelated round sample.
    for field in ('fk_fd_margin','fk_fd_diff','fk_fd_per_round','total_fk','total_fd'):
        advanced[field] = None
    ace = career_comparison(data)
    # A fresh map scope must not mask an older career snapshot in a filtered report.
    dates.append(ace['collected_at'])
    valid_dates = [stamp for stamp in dates if stamp]
    return {'form': data.get('form', []), 'maps': maps, 'ace': ace,
            'recent_matches': data.get('recent_matches', []),
            'roster': career_roster(data),
            'advanced': advanced, 'updated_at': min(valid_dates) if valid_dates else data.get('updated_at'),
            'stale': bool(data.get('last_error')) or any(expired(d) for d in dates)
                     or any(key in data.get('failed_scopes', []) for key in set(keys) | {'all'}),
            'event_ids': keys, 'players_available': ace['available']}


def career_roster(data):
    scope = data.get('scopes', {}).get('all', {})
    if not scope.get('career_roster_verified'):
        return []
    rows = []
    for pid, player in scope.get('players', {}).items():
        has_stats = player.get('rounds', 0) > 0
        stats = career_player_stats({**player, 'player_id': pid})
        rows.append({**stats, 'nickname': player.get('name', pid), 'player_id': pid,
                     'available': has_stats, 'scope': 'career', 'collected_at': scope.get('collected_at')})
    return sorted(rows, key=lambda p: (not p['available'], -(p['acs'] or 0), -(p['rounds'] or 0), p['player_id']))


def full_analysis(team_a_id, team_b_id, event_ids, map_pool):
    records = get_analysis_teams([team_a_id, team_b_id])
    if any(not records.get(tid, {}).get('scopes') for tid in (team_a_id, team_b_id)):
        raise AnalysisNotReady('이 팀의 전력 분석을 준비 중입니다. 다음 업데이트 후 다시 선택해주세요.')
    a = aggregate_team(records[team_a_id], event_ids)
    b = aggregate_team(records[team_b_id], event_ids)
    probability = None
    return {'form_a': a['form'], 'form_b': b['form'], 'maps_a': a['maps'], 'maps_b': b['maps'],
            'recent_a': a['recent_matches'], 'recent_b': b['recent_matches'],
            'roster_a': a['roster'], 'roster_b': b['roster'],
            'logo_a': records[team_a_id].get('logo'), 'logo_b': records[team_b_id].get('logo'),
            'ace_a': a['ace'], 'ace_b': b['ace'], 'adv_a': a['advanced'], 'adv_b': b['advanced'],
            'simulation': simulate_banpick(a['maps'], b['maps'], map_pool) if a['advanced']['total_played'] and b['advanced']['total_played'] else {'bans': [], 'picks': []}, 'probability': probability,
            'updated_at': min(a['updated_at'], b['updated_at']), 'stale': a['stale'] or b['stale'],
            'players_available': a['players_available'] and b['players_available'],
            'event_ids': sorted(set(event_ids)) if event_ids else None}
