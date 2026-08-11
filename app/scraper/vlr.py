import re
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.config import load_tier_config
from app.scraper.http import request_with_retry
from app.scraper.parsers import (
    clean_text, safe_int, safe_float, parse_column_indices_from_header,
    parse_player_column_indices_from_header, parse_matches_list,
    parse_match_details, parse_live_score
)
from app.scraper.metrics import (
    normalize_team_name, team_matches, calculate_advanced_metrics,
    find_ace_player_from_stats
)

def get_matches():
    s_keywords, a_keywords = load_tier_config()
    url = "https://www.vlr.gg/matches"
    res = request_with_retry(url)
    return parse_matches_list(res.text, s_keywords, a_keywords)

def get_match_details(match_url):
    res = request_with_retry(match_url)
    return parse_match_details(res.text, match_url)

def get_event_map_pool(event_id):
    if not event_id:
        return []
    url = f"https://www.vlr.gg/event/agents/{event_id}"
    try:
        res = request_with_retry(url)
    except Exception:
        return []
    if res.status_code != 200:
        return []

    from app.config import ALL_KNOWN_MAPS
    soup = BeautifulSoup(res.text, 'html.parser')
    detected = set()

    for container in soup.find_all(class_=['mod-agents', 'vm-stats-container', 'mod-team-maps', 'mod-map-pool']):
        for cell in container.find_all(['th', 'td', 'div', 'span']):
            cell_text = clean_text(cell.get_text())
            if not cell_text:
                continue
            for m in ALL_KNOWN_MAPS:
                if m not in detected and re.search(r'\b' + re.escape(m) + r'\b', cell_text, re.I):
                    detected.add(m)

    if not detected:
        page_text = soup.get_text(' ')
        for m in ALL_KNOWN_MAPS:
            if re.search(r'\b' + re.escape(m) + r'\b', page_text, re.I):
                detected.add(m)

    return sorted(detected)

def get_team_events(team_id):
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/stats/{team_id}"
    try:
        res = request_with_retry(url)
    except Exception:
        return []
    if res.status_code != 200:
        return []

    soup = BeautifulSoup(res.text, 'html.parser')
    events = []
    selects = soup.find_all('select')
    for select in selects:
        options = select.find_all('option')
        for opt in options:
            val = opt.get('value', '')
            text = clean_text(opt.get_text())
            if val and val != 'all' and text and text != 'All Events':
                events.append({"id": val, "name": text})
    return events

def get_live_score(match_url):
    try:
        res = request_with_retry(match_url)
    except Exception:
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    if res.status_code != 200:
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    return parse_live_score(res.text)

def get_team_form(team_id, max_results=10):
    if not team_id:
        return []
    results = []
    team_name_norm = ""
    MAX_PAGES = 5

    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.vlr.gg/team/matches/{team_id}/?page={page}" if page > 1 else f"https://www.vlr.gg/team/{team_id}"
        try:
            res = request_with_retry(url)
        except Exception:
            break
        if res.status_code != 200:
            break

        soup = BeautifulSoup(res.text, 'html.parser')
        if not team_name_norm:
            team_header = soup.find(class_='team-header-name')
            team_name_str = clean_text(team_header.get_text()) if team_header else ""
            team_name_norm = normalize_team_name(team_name_str)

        links = soup.find_all('a', href=True)
        found_any = False
        for a in links:
            href = a['href']
            parts = href.split('/')
            if len(parts) >= 3 and parts[1].isdigit() and '-vs-' in parts[2]:
                team_names = a.find_all(class_='m-item-team-name')
                if len(team_names) < 2:
                    continue
                team_a = clean_text(team_names[0].get_text())
                team_b = clean_text(team_names[1].get_text())
                result_div = a.find(class_='m-item-result')
                if not result_div:
                    continue
                score_text = clean_text(result_div.get_text())
                score_match = re.search(r'(\d+)\s*[:-]\s*(\d+)', score_text)
                if not score_match:
                    continue
                score_a = int(score_match.group(1))
                score_b = int(score_match.group(2))

                team_a_norm = normalize_team_name(team_a)
                team_b_norm = normalize_team_name(team_b)

                outcome = "L"
                opponent = team_b
                if team_name_norm:
                    if team_matches(team_name_norm, team_a_norm):
                        outcome = "W" if score_a > score_b else "L"
                        opponent = team_b
                    elif team_matches(team_name_norm, team_b_norm):
                        outcome = "W" if score_b > score_a else "L"
                        opponent = team_a
                    else:
                        continue
                else:
                    outcome = "W" if score_a > score_b else "L"

                results.append(f"{outcome} ({score_a}-{score_b}) vs {opponent}")
                found_any = True
                if len(results) >= max_results:
                    break

        if len(results) >= max_results or not found_any:
            break

    return results

def get_single_team_stats_page(team_id, event_id=None):
    url = f"https://www.vlr.gg/team/stats/{team_id}"
    if event_id:
        url += f"/?event_id={event_id}"
    try:
        res = request_with_retry(url)
    except Exception:
        return {}
    if res.status_code != 200:
        return {}

    soup = BeautifulSoup(res.text, 'html.parser')
    table = soup.find('table', class_='mod-team-maps')
    if not table:
        return {}
    tbody = table.find('tbody')
    if not tbody:
        return {}

    col_map = parse_column_indices_from_header(table)
    required_keys = ('map', 'w', 'l', 'atk_won', 'atk_lost', 'def_won', 'def_lost')
    missing_keys = [k for k in required_keys if k not in col_map]
    if missing_keys:
        raise ValueError(f"Team stats column mapping failed: Missing keys {missing_keys}")

    required_indices = [col_map[k] for k in required_keys]
    min_cells_needed = max(required_indices) + 1

    maps_data = {}
    for row in tbody.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) < min_cells_needed:
            continue
        raw_map = clean_text(cells[col_map.get('map', 0)].get_text())
        map_name = raw_map.split('\n')[0].strip()
        played = safe_int(cells[col_map.get('map', 0)].get_text())
        if played == 0:
            m_played = re.search(r'(\d+)', raw_map)
            if m_played:
                played = int(m_played.group(1))

        atk_rounds_won = safe_int(cells[col_map.get('atk_won', 8)].get_text())
        atk_rounds_lost = safe_int(cells[col_map.get('atk_lost', 9)].get_text())
        def_rounds_won = safe_int(cells[col_map.get('def_won', 11)].get_text())
        def_rounds_lost = safe_int(cells[col_map.get('def_lost', 12)].get_text())
        w = safe_int(cells[col_map.get('w', 3)].get_text())
        l = safe_int(cells[col_map.get('l', 4)].get_text())

        maps_data[map_name] = {
            "played": played,
            "w": w,
            "l": l,
            "atk_won": atk_rounds_won,
            "atk_total": atk_rounds_won + atk_rounds_lost,
            "def_won": def_rounds_won,
            "def_total": def_rounds_won + def_rounds_lost
        }

    return maps_data

def get_team_maps_stats(team_id, event_ids=None):
    if not event_ids:
        return get_single_team_stats_page(team_id)

    aggregated = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_event = {
            executor.submit(get_single_team_stats_page, team_id, ev_id): ev_id
            for ev_id in event_ids
        }
        for future in as_completed(future_to_event):
            ev_data = future.result()
            for map_name, stats in ev_data.items():
                if map_name not in aggregated:
                    aggregated[map_name] = {
                        "played": 0, "w": 0, "l": 0,
                        "atk_won": 0, "atk_total": 0,
                        "def_won": 0, "def_total": 0
                    }
                aggregated[map_name]["played"] += stats.get("played", 0)
                aggregated[map_name]["w"] += stats.get("w", 0)
                aggregated[map_name]["l"] += stats.get("l", 0)
                aggregated[map_name]["atk_won"] += stats.get("atk_won", 0)
                aggregated[map_name]["atk_total"] += stats.get("atk_total", 0)
                aggregated[map_name]["def_won"] += stats.get("def_won", 0)
                aggregated[map_name]["def_total"] += stats.get("def_total", 0)

    return aggregated

def get_player_stats_page(player_id, event_id=None):
    url = f"https://www.vlr.gg/player/{player_id}"
    if event_id:
        url += f"/?event_id={event_id}"
    try:
        res = request_with_retry(url)
    except Exception:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}
    if res.status_code != 200:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}

    soup = BeautifulSoup(res.text, 'html.parser')
    table = soup.find('table', class_='mod-player-summary') or soup.find('table', class_='wf-table')
    if not table:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}
    tbody = table.find('tbody')
    if not tbody:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}

    col_map = parse_player_column_indices_from_header(table)
    required_keys = ('agent', 'rounds', 'acs', 'kills', 'deaths')
    missing_keys = [k for k in required_keys if k not in col_map]
    if missing_keys:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}

    required_indices = [col_map[k] for k in required_keys]
    min_cells_needed = max(required_indices) + 1

    player_data = {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}
    for row in tbody.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) < min_cells_needed:
            continue
        agent_idx = col_map.get('agent', 0)
        img = cells[agent_idx].find('img')
        agent_name = img.get('alt', 'Unknown').lower() if img else 'unknown'
        rounds = safe_int(cells[col_map.get('rounds', 2)].get_text())
        acs = safe_float(clean_text(cells[col_map.get('acs', 4)].get_text()))
        kills = safe_int(cells[col_map.get('kills', 11)].get_text())
        deaths = safe_int(cells[col_map.get('deaths', 12)].get_text())
        fk = safe_int(cells[col_map.get('fk', 14)].get_text()) if len(cells) > col_map.get('fk', 14) else 0
        fd = safe_int(cells[col_map.get('fd', 15)].get_text()) if len(cells) > col_map.get('fd', 15) else 0

        player_data["rounds"] += rounds
        player_data["weighted_acs"] += acs * rounds
        player_data["kills"] += kills
        player_data["deaths"] += deaths
        player_data["fk"] += fk
        player_data["fd"] += fd
        player_data["agents"][agent_name] = player_data["agents"].get(agent_name, 0) + rounds

    return player_data

def get_player_stats(player_id, event_ids=None):
    if not event_ids:
        return get_player_stats_page(player_id)

    aggregated = {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "fk": 0, "fd": 0, "agents": {}}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_event = {
            executor.submit(get_player_stats_page, player_id, ev_id): ev_id
            for ev_id in event_ids
        }
        for future in as_completed(future_to_event):
            pdata = future.result()
            aggregated["rounds"] += pdata.get("rounds", 0)
            aggregated["weighted_acs"] += pdata.get("weighted_acs", 0)
            aggregated["kills"] += pdata.get("kills", 0)
            aggregated["deaths"] += pdata.get("deaths", 0)
            aggregated["fk"] += pdata.get("fk", 0)
            aggregated["fd"] += pdata.get("fd", 0)
            for ag, r in pdata.get("agents", {}).items():
                aggregated["agents"][ag] = aggregated["agents"].get(ag, 0) + r

    return aggregated

def get_team_roster(team_id):
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/{team_id}"
    try:
        res = request_with_retry(url)
    except Exception:
        return []
    if res.status_code != 200:
        return []

    soup = BeautifulSoup(res.text, 'html.parser')
    players = []
    items = soup.find_all(class_='team-roster-item')
    for item in items:
        a = item.find('a', href=True)
        if a and '/player' in a['href']:
            player_id = a['href'].split('/')[2]
            alias_elem = a.find(class_='team-roster-item-name-alias')
            nickname = clean_text(alias_elem.get_text()) if alias_elem else clean_text(a.get_text()).split('\n')[0].strip()
            players.append({"id": player_id, "name": nickname, "url": f"https://www.vlr.gg{a['href']}"})

    return players

def get_team_advanced_metrics(team_id, event_ids=None):
    default_res = {
        "map_win_rate": 50.0,
        "pistol_win_rate": 50.0,
        "fk_fd_margin": 0.0,
        "fk_fd_diff": 0,
        "fk_fd_per_round": 0.0,
        "total_played": 0,
        "total_wins": 0,
        "total_fk": 0,
        "total_fd": 0,
        "top_compositions": []
    }
    if not team_id:
        return default_res

    maps_data = get_team_maps_stats(team_id, event_ids)
    total_fk = 0
    total_fd = 0
    total_rounds = 0

    try:
        roster = get_team_roster(team_id)
        for player in roster:
            try:
                pstats = get_player_stats(player.get('id', ''), event_ids)
                p_rounds = pstats.get('rounds', 0)
                if p_rounds > 0:
                    total_fk += pstats.get('fk', 0)
                    total_fd += pstats.get('fd', 0)
                    total_rounds += p_rounds
            except Exception:
                continue
    except Exception:
        pass

    return calculate_advanced_metrics(maps_data, total_fk, total_fd, total_rounds)
