"""Background-only source collection. Store counts, not averaged percentages."""
import re
import threading
from concurrent.futures import Future
from bs4 import BeautifulSoup

from app.db import get_analysis_source, save_analysis_source
from app.scraper.http import request_with_retry
from app.scraper.parsers import (clean_text, safe_int, safe_float,
                                 parse_column_indices_from_header, parse_player_column_indices_from_header)
from app.scraper.metrics import team_matches
from app.config import ALL_KNOWN_MAPS

_flights = {}
_lock = threading.Lock()
refresh_started_at = None


def source(key, fetch):
    cached = get_analysis_source(key, not_before=refresh_started_at)
    if cached is not None:
        return cached
    with _lock:
        leader = key not in _flights
        if leader:
            _flights[key] = Future()
        future = _flights[key]
    if not leader:
        return future.result(timeout=90)
    try:
        value = fetch()
        save_analysis_source(key, value)
        future.set_result(value)
        return value
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _flights.pop(key, None)


def page(url):
    response = request_with_retry(url)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'html.parser')


def parse_maps(soup):
    table = soup.select_one('table.mod-team-maps')
    if table is None:
        raise ValueError('Team maps table missing')
    cols = parse_column_indices_from_header(table)
    maps = {}
    for row in table.select('tbody tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) <= max(cols.values()):
            continue
        raw = clean_text(cells[cols['map']].get_text())
        name = next((m for m in ALL_KNOWN_MAPS if re.search(r'\b'+re.escape(m)+r'\b', raw, re.I)), None)
        if not name:
            continue
        number = re.search(r'\((\d+)\)', raw)
        counts = {key: safe_int(cells[cols[key]].get_text()) for key in ('w','l','atk_won','atk_lost','def_won','def_lost')}
        maps[name] = {'played': int(number[1]) if number else counts['w'] + counts['l'],
                      'w': counts['w'], 'l': counts['l'], 'atk_won': counts['atk_won'],
                      'atk_total': counts['atk_won'] + counts['atk_lost'], 'def_won': counts['def_won'],
                      'def_total': counts['def_won'] + counts['def_lost']}
    return maps


def team_overview(team_id):
    def fetch():
        soup = page(f'https://www.vlr.gg/team/stats/{team_id}')
        selector = soup.select_one('select[name="event_id"], select.filter-event')
        if selector is None:
            raise ValueError('Team events selector missing')
        return {'maps': parse_maps(soup), 'available_events': [o['value'] for o in selector.select('option[value]') if o['value'].isdigit()]}
    return source(f'overview:{team_id}', fetch)


def event_maps(team_id, event_id):
    return source(f'maps:{team_id}:{event_id}', lambda: parse_maps(page(f'https://www.vlr.gg/team/stats/{team_id}/?event_id={event_id}')))


def parse_profile(soup):
    header = soup.select_one('.team-header-name')
    if header is None:
        raise ValueError('Team profile missing')
    name = clean_text(header.get_text())
    roster = {}
    for item in soup.select('.team-roster-item'):
        link = item.select_one('a[href^="/player/"]')
        if link:
            alias = link.select_one('.team-roster-item-name-alias')
            roster[link['href'].split('/')[2]] = clean_text((alias or link).get_text())
    form = []
    for match in soup.select('a.m-item'):
        score = match.select_one('.m-item-result')
        teams = match.select('.m-item-team-name')
        if score is None or len(teams) != 2:
            continue
        result = re.search(r'(\d+)\s*[:-]\s*(\d+)', clean_text(score.get_text()))
        if not result:
            continue
        a, b = [clean_text(t.get_text()) for t in teams]
        sa, sb = map(int, result.groups())
        if team_matches(name, a):
            own, other, opponent = sa, sb, b
        elif team_matches(name, b):
            own, other, opponent = sb, sa, a
        else:
            continue
        form.append(f"{'W' if own > other else 'L'} ({own}-{other}) vs {opponent}")
    return {'name': name, 'roster': roster, 'form': form[:5]}


def team_profile(team_id):
    return source(f'profile:{team_id}', lambda: parse_profile(page(f'https://www.vlr.gg/team/{team_id}')))


def empty_player():
    return {'rounds': 0, 'weighted_acs': 0, 'kills': 0, 'deaths': 0, 'fk': 0, 'fd': 0, 'agents': {}}


def parse_player(soup):
    table = soup.select_one('table.mod-player-summary, table.mod-agent-rows')
    if table is None:
        # Coaches and staff profiles legitimately have no player statistics.
        if soup.select_one('.player-header h1, .player-header-name'):
            return empty_player()
        raise ValueError('Player statistics missing')
    cols = parse_player_column_indices_from_header(table)
    player = empty_player()
    for row in table.select('tbody tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) <= max(cols.values()):
            continue
        rounds = safe_int(cells[cols['rounds']].get_text())
        player['rounds'] += rounds
        player['weighted_acs'] += safe_float(cells[cols['acs']].get_text()) * rounds
        for key in ('kills','deaths','fk','fd'):
            player[key] += safe_int(cells[cols[key]].get_text())
        img = cells[cols['agent']].find('img')
        agent = (img.get('alt') or img.get('src','').split('/')[-1].split('.')[0]) if img else 'unknown'
        player['agents'][agent.lower()] = player['agents'].get(agent.lower(), 0) + rounds
    return player


def player_totals(player_id):
    # Bare player profiles default to a recent time window, not career totals.
    return source(f'player-all:{player_id}', lambda: parse_player(page(f'https://www.vlr.gg/player/{player_id}/?timespan=all')))


def parse_event_players(soup):
    table = soup.select_one('table.st-table')
    if table is None:
        if 'No stats available' in soup.get_text():
            return {'_unavailable': True}
        raise ValueError('Event player statistics missing')
    players = {}
    for row in table.select('tbody tr'):
        link = row.select_one('a[href^="/player/"]')
        cells = {c.get('data-col'): c for c in row.find_all('td', recursive=False)}
        if not link or not {'rnd','acs','k','d','fk','fd'} <= cells.keys():
            continue
        player = empty_player()
        player['rounds'] = safe_int(cells['rnd'].get_text())
        player['weighted_acs'] = safe_float(cells['acs'].get_text()) * player['rounds']
        for key, col in (('kills','k'),('deaths','d'),('fk','fk'),('fd','fd')):
            player[key] = safe_int(cells[col].get_text())
        for agent in row.select('.st-agent'):
            img = agent.find('img')
            if img:
                name = img.get('src','').split('/')[-1].split('.')[0]
                player['agents'][name] = safe_float(agent.get_text()) * player['rounds'] / 100
        players[link['href'].split('/')[2]] = player
    if not players:
        raise ValueError('Event player rows missing')
    return players


def event_players(event_id):
    # One leaderboard request supplies every player in a tournament.
    return source(f'event-players:{event_id}', lambda: parse_event_players(page(f'https://www.vlr.gg/event/stats/{event_id}')))
