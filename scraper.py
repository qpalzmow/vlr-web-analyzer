import requests
from bs4 import BeautifulSoup
import re
import urllib.parse as urlparse
import time

# User agent to mimic a real browser session
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def clean_text(text):
    if not text:
        return ""
    # Remove excessive spaces and newlines
    return re.sub(r'\s+', ' ', text).strip()

def safe_int(s, default=0):
    if not s:
        return default
    s_clean = clean_text(s)
    try:
        # Strip any formatting or whitespace and keep only numbers/hyphens
        s_nums = re.sub(r'[^\d-]', '', s_clean)
        if s_nums:
            return int(s_nums)
    except Exception:
        pass
    return default

def get_matches():
    """Scrapes vlr.gg/matches, filters by Tier, and groups matches."""
    url = "https://www.vlr.gg/matches"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except Exception as e:
        raise Exception(f"Network error while fetching matches: {e}")
        
    if res.status_code != 200:
        raise Exception(f"VLR.gg returned status code {res.status_code}")
        
    soup = BeautifulSoup(res.text, 'html.parser')
    matches = []
    
    # S-Tier and A-Tier keywords
    s_keywords = ["Champions", "Masters", "International League", "Pacific", "Americas", "EMEA", "CN", "World Cup", "EWC", "Championship"]
    a_keywords = ["Challengers", "Game Changers"]
    
    # Structure on vlr.gg matches page:
    # <div class="wf-label">Today</div>
    # <div class="wf-card">...</div>
    labels = soup.find_all(class_='wf-label')
    
    for label in labels:
        date_str = clean_text(label.get_text())
        card = label.find_next_sibling(class_='wf-card')
        if not card:
            card = label.find_next(class_='wf-card')
            
        if card:
            # Sibling check to make sure the card belongs to this label
            prev_label = card.find_previous(class_='wf-label')
            if prev_label and prev_label != label:
                continue
                
            match_items = card.find_all('a', class_='match-item')
            for item in match_items:
                href = item.get('href', '')
                if not href:
                    continue
                
                parts = href.split('/')
                match_id = parts[1] if len(parts) > 1 else ""
                full_url = f"https://www.vlr.gg{href}"
                
                # Event Name
                event_elem = item.find(class_='match-item-event')
                event_name = clean_text(event_elem.get_text()) if event_elem else "Unknown Event"
                
                # Team Names
                team_elems = item.find_all(class_='match-item-vs-team-name')
                if len(team_elems) >= 2:
                    team_a = clean_text(team_elems[0].get_text())
                    team_b = clean_text(team_elems[1].get_text())
                else:
                    team_a = "Team A"
                    team_b = "Team B"
                    
                # Time
                time_elem = item.find(class_='match-item-time')
                match_time = clean_text(time_elem.get_text()) if time_elem else "TBD"
                
                # Determine tier
                tier = "Other"
                event_lower = event_name.lower()
                if any(kw.lower() in event_lower for kw in s_keywords):
                    tier = "S-Tier"
                elif any(kw.lower() in event_lower for kw in a_keywords):
                    tier = "A-Tier"
                
                matches.append({
                    "id": match_id,
                    "url": full_url,
                    "event": event_name,
                    "team_a": team_a,
                    "team_b": team_b,
                    "time": match_time,
                    "date": date_str,
                    "tier": tier
                })
                
    # Fallback if no matches scraped due to layout changes
    if not matches:
        match_items = soup.find_all('a', class_='match-item')
        for item in match_items:
            href = item.get('href', '')
            if not href:
                continue
            parts = href.split('/')
            match_id = parts[1] if len(parts) > 1 else ""
            full_url = f"https://www.vlr.gg{href}"
            
            event_elem = item.find(class_='match-item-event')
            event_name = clean_text(event_elem.get_text()) if event_elem else "Unknown Event"
            
            team_elems = item.find_all(class_='match-item-vs-team-name')
            if len(team_elems) >= 2:
                team_a = clean_text(team_elems[0].get_text())
                team_b = clean_text(team_elems[1].get_text())
            else:
                team_a = "Team A"
                team_b = "Team B"
                
            time_elem = item.find(class_='match-item-time')
            match_time = clean_text(time_elem.get_text()) if time_elem else "TBD"
            
            tier = "Other"
            event_lower = event_name.lower()
            if any(kw.lower() in event_lower for kw in s_keywords):
                tier = "S-Tier"
            elif any(kw.lower() in event_lower for kw in a_keywords):
                tier = "A-Tier"
                
            matches.append({
                "id": match_id,
                "url": full_url,
                "event": event_name,
                "team_a": team_a,
                "team_b": team_b,
                "time": match_time,
                "date": "Upcoming",
                "tier": tier
            })
            
    return matches

def get_match_details(match_url):
    """Scrapes match details to find Team IDs and names."""
    try:
        res = requests.get(match_url, headers=HEADERS, timeout=10)
    except Exception as e:
        raise Exception(f"Network error while fetching match details: {e}")
        
    if res.status_code != 200:
        raise Exception(f"Failed to fetch match details. Status: {res.status_code}")
        
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # Locate team IDs from header
    header_teams = []
    header_container = soup.find(class_='match-header')
    if header_container:
        for a in header_container.find_all('a', href=True):
            href = a['href']
            if '/team/' in href:
                parts = href.split('/')
                for i, part in enumerate(parts):
                    if part == 'team' and i + 1 < len(parts) and parts[i+1].isdigit():
                        team_id = parts[i+1]
                        team_name = parts[i+2] if i + 2 < len(parts) else "Team"
                        if team_id not in [t[0] for t in header_teams]:
                            header_teams.append((team_id, team_name))
                            
    # Fallback to page-wide search
    if len(header_teams) < 2:
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/team/') and not href.startswith('/team/stats/'):
                parts = href.split('/')
                if len(parts) >= 3 and parts[2].isdigit():
                    team_id = parts[2]
                    team_name = parts[3] if len(parts) > 3 else "Team"
                    if team_id not in [t[0] for t in header_teams]:
                        header_teams.append((team_id, team_name))
                        
    team_a_id = header_teams[0][0] if len(header_teams) > 0 else ""
    team_a_name = header_teams[0][1] if len(header_teams) > 0 else ""
    team_b_id = header_teams[1][0] if len(header_teams) > 1 else ""
    team_b_name = header_teams[1][1] if len(header_teams) > 1 else ""
    
    # Locate event ID from page links
    event_id = ""
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/event/' in href:
            parts = href.split('/')
            for i, part in enumerate(parts):
                if part == 'event' and i + 1 < len(parts) and parts[i+1].isdigit():
                    event_id = parts[i+1]
                    break
            if event_id:
                break
    
    return {
        "team_a_id": team_a_id,
        "team_a_name": team_a_name,
        "team_b_id": team_b_id,
        "team_b_name": team_b_name,
        "event_id": event_id
    }

def get_event_map_pool(event_id):
    """Scrapes the VLR tournament agents page to detect the active map pool for this tournament."""
    if not event_id:
        return []
    url = f"https://www.vlr.gg/event/agents/{event_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except Exception:
        return []
        
    if res.status_code != 200:
        return []
        
    soup = BeautifulSoup(res.text, 'html.parser')
    all_known_maps = ["Ascent", "Bind", "Breeze", "Haven", "Icebox", "Lotus", "Split", "Sunset", "Abyss", "Fracture", "Pearl", "Summit"]
    
    page_text = soup.get_text(' ')
    detected = []
    for m in all_known_maps:
        if re.search(r'\b' + re.escape(m) + r'\b', page_text, re.I):
            detected.append(m)
            
    return sorted(detected)

def get_team_events(team_id):
    """Scrapes the event dropdown filters from the team map stats page."""
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/stats/{team_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
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
            name = clean_text(opt.get_text())
            if val.isdigit() and val != 'all':
                events.append({"id": val, "name": name})
                
    if not events:
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '?event=' in href or '?event_id=' in href:
                parsed = urlparse.urlparse(href)
                params = urlparse.parse_qs(parsed.query)
                event_id = params.get('event', [None])[0] or params.get('event_id', [None])[0]
                if event_id and event_id.isdigit():
                    name = clean_text(a.get_text())
                    events.append({"id": event_id, "name": name})
                    
    seen = set()
    deduped = []
    for e in events:
        if e['id'] not in seen:
            seen.add(e['id'])
            deduped.append(e)
            
    return deduped

def get_team_roster(team_id):
    """Scrapes the team roster, filtering out staff members."""
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/{team_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except Exception:
        return []
        
    if res.status_code != 200:
        return []
        
    soup = BeautifulSoup(res.text, 'html.parser')
    players = []
    
    roster_items = soup.find_all(class_='team-roster-item')
    for item in roster_items:
        role_elem = item.find(class_='team-roster-item-role')
        role_text = role_elem.get_text(strip=True).lower() if role_elem else ""
        
        item_text = item.get_text(' ', strip=True).lower()
        is_staff = any(kw in item_text for kw in ["coach", "manager", "analyst", "staff", "director", "owner", "inactive"])
        
        if is_staff:
            continue
            
        a = item.find('a', href=True)
        if a:
            href = a['href']
            if href.startswith('/player/'):
                parts = href.split('/')
                player_id = parts[2] if len(parts) > 2 else ""
                
                alias_elem = item.find(class_='team-roster-item-name-alias')
                if alias_elem:
                    nickname = clean_text(alias_elem.get_text())
                else:
                    nickname = clean_text(a.get_text())
                    nickname = nickname.split('\n')[0].strip()
                
                players.append({
                    "id": player_id,
                    "name": nickname,
                    "url": f"https://www.vlr.gg{href}"
                })
                
    return players

def get_team_form(team_id):
    """Scrapes the last 5 completed match results from the team page, including clean opponent names."""
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/{team_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except Exception:
        return []
        
    if res.status_code != 200:
        return []
        
    soup = BeautifulSoup(res.text, 'html.parser')
    results = []
    
    # Get team name from header to identify which team is which
    team_header = soup.find(class_='team-header-name')
    team_name_str = clean_text(team_header.get_text()) if team_header else ""
    team_name_lower = team_name_str.lower()
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        parts = href.split('/')
        if len(parts) >= 3 and parts[1].isdigit() and '-vs-' in parts[2]:
            # Locate team name spans
            team_names = a.find_all(class_='m-item-team-name')
            if len(team_names) < 2:
                continue
                
            team_a = clean_text(team_names[0].get_text())
            team_b = clean_text(team_names[1].get_text())
            
            # Locate result score
            result_div = a.find(class_='m-item-result')
            if not result_div:
                continue
                
            score_text = clean_text(result_div.get_text())
            # Match score format (e.g. "2:0" or "0:2" or "3-2")
            score_match = re.search(r'(\d+)\s*[:-]\s*(\d+)', score_text)
            if not score_match:
                # If it's a scheduled match ("TBD" or timezone/time), skip
                continue
                
            score_a = int(score_match.group(1))
            score_b = int(score_match.group(2))
            
            team_a_lower = team_a.lower()
            team_b_lower = team_b.lower()
            
            opponent = team_b
            outcome = "L"
            
            if team_name_lower:
                if team_name_lower in team_a_lower or team_a_lower in team_name_lower:
                    outcome = "W" if score_a > score_b else "L"
                    opponent = team_b
                elif team_name_lower in team_b_lower or team_b_lower in team_name_lower:
                    outcome = "W" if score_b > score_a else "L"
                    opponent = team_a
                else:
                    outcome = "W" if score_a > score_b else "L"
                    opponent = team_b
            else:
                outcome = "W" if score_a > score_b else "L"
                opponent = team_b
                
            score_str = f"{score_a}-{score_b}"
            results.append(f"{outcome} ({score_str}) vs {opponent}")
            
            if len(results) >= 5:
                break
                
    return results

def get_single_team_stats_page(team_id, event_id=None):
    """Scrapes the map statistics page for a single event_id."""
    url = f"https://www.vlr.gg/team/stats/{team_id}"
    if event_id:
        url += f"/?event_id={event_id}"
        
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
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
        
    maps_data = {}
    rows = tbody.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 13:
            continue
            
        map_name_raw = clean_text(cells[0].get_text())
        map_match = re.match(r'^([A-Za-z0-9]+)', map_name_raw)
        if not map_match:
            continue
        map_name = map_match.group(1)
        
        played_match = re.search(r'\((\d+)\)', map_name_raw)
        played = safe_int(played_match.group(1)) if played_match else 0
        
        atk_rounds_won = safe_int(cells[8].get_text())
        atk_rounds_lost = safe_int(cells[9].get_text())
        
        def_rounds_won = safe_int(cells[11].get_text())
        def_rounds_lost = safe_int(cells[12].get_text())
        
        w = safe_int(cells[3].get_text())
        l = safe_int(cells[4].get_text())
        
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
    """Fetches map stats, aggregates them if multiple event IDs are checked."""
    if not event_ids:
        return get_single_team_stats_page(team_id)
        
    aggregated = {}
    for ev_id in event_ids:
        time.sleep(0.5)
        ev_data = get_single_team_stats_page(team_id, ev_id)
        for map_name, stats in ev_data.items():
            if map_name not in aggregated:
                aggregated[map_name] = {
                    "played": 0,
                    "w": 0,
                    "l": 0,
                    "atk_won": 0,
                    "atk_total": 0,
                    "def_won": 0,
                    "def_total": 0
                }
            aggregated[map_name]["played"] += stats["played"]
            aggregated[map_name]["w"] += stats.get("w", 0)
            aggregated[map_name]["l"] += stats.get("l", 0)
            aggregated[map_name]["atk_won"] += stats["atk_won"]
            aggregated[map_name]["atk_total"] += stats["atk_total"]
            aggregated[map_name]["def_won"] += stats["def_won"]
            aggregated[map_name]["def_total"] += stats["def_total"]
            
    return aggregated

def get_player_stats_page(player_id, event_id=None):
    """Scrapes statistics from a player page for a single event_id."""
    url = f"https://www.vlr.gg/player/{player_id}"
    if event_id:
        url += f"/?event_id={event_id}"
        
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
    except Exception:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "agents": {}}
        
    if res.status_code != 200:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "agents": {}}
        
    soup = BeautifulSoup(res.text, 'html.parser')
    table = soup.find('table', class_='mod-agent-rows')
    if not table:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "agents": {}}
        
    tbody = table.find('tbody')
    if not tbody:
        return {"rounds": 0, "weighted_acs": 0, "kills": 0, "deaths": 0, "agents": {}}
        
    rows = tbody.find_all('tr')
    player_data = {
        "rounds": 0,
        "weighted_acs": 0,
        "kills": 0,
        "deaths": 0,
        "agents": {}
    }
    
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 13:
            continue
            
        img = cells[0].find('img')
        agent_name = img.get('alt', 'Unknown').lower() if img else 'unknown'
        
        rounds = safe_int(cells[2].get_text())
        
        acs_str = clean_text(cells[4].get_text())
        try:
            acs = float(re.sub(r'[^\d.]', '', acs_str)) if acs_str else 0.0
        except Exception:
            acs = 0.0
            
        kills = safe_int(cells[11].get_text())
        deaths = safe_int(cells[12].get_text())
        
        player_data["rounds"] += rounds
        player_data["weighted_acs"] += acs * rounds
        player_data["kills"] += kills
        player_data["deaths"] += deaths
        
        if agent_name not in player_data["agents"]:
            player_data["agents"][agent_name] = 0
        player_data["agents"][agent_name] += rounds
        
    return player_data

def get_player_stats(player_id, event_ids=None):
    """Fetches player statistics aggregated across selected event IDs or from the main player page."""
    if not event_ids:
        return get_player_stats_page(player_id)
        
    aggregated = {
        "rounds": 0,
        "weighted_acs": 0.0,
        "kills": 0,
        "deaths": 0,
        "agents": {}
    }
    
    for ev_id in event_ids:
        time.sleep(0.3)
        ev_data = get_player_stats_page(player_id, ev_id)
        aggregated["rounds"] += ev_data["rounds"]
        aggregated["weighted_acs"] += ev_data["weighted_acs"]
        aggregated["kills"] += ev_data["kills"]
        aggregated["deaths"] += ev_data["deaths"]
        
        for agent, rounds in ev_data["agents"].items():
            if agent not in aggregated["agents"]:
                aggregated["agents"][agent] = 0
            aggregated["agents"][agent] += rounds
            
    # Fallback to main page if no games played in the selected events
    if aggregated["rounds"] == 0:
        return get_player_stats_page(player_id)
        
    return aggregated

def get_live_score(match_url):
    """Scrapes map scores, series score, and status from the match page."""
    try:
        res = requests.get(match_url, headers=HEADERS, timeout=10)
    except Exception:
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
        
    if res.status_code != 200:
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
        
    soup = BeautifulSoup(res.text, 'html.parser')
    
    # 1. Parse Series Score
    score_left = "0"
    score_right = "0"
    vs_score_container = soup.find(class_='match-header-vs-score')
    if vs_score_container:
        spans = vs_score_container.find_all('span')
        score_spans = []
        for s in spans:
            cls = s.get('class', [])
            if any('match-header-vs-score-' in c for c in cls) and 'colon' not in ''.join(cls):
                score_spans.append(s)
        if len(score_spans) >= 2:
            score_left = clean_text(score_spans[0].get_text())
            score_right = clean_text(score_spans[1].get_text())
            
    # 2. Parse Series Game Status (final, live, upcoming)
    status = "upcoming"
    vs_notes = soup.find_all(class_='match-header-vs-note')
    status_texts = [clean_text(n.get_text()).lower() for n in vs_notes]
    
    # Restrict broad live/final searching to the match-header block to prevent matching navbar links
    header = soup.find(class_='match-header')
    header_text = clean_text(header.get_text()).lower() if header else ""
    
    if any('final' in t for t in status_texts) or 'final' in header_text:
        status = "final"
    elif any('live' in t for t in status_texts) or 'live' in header_text:
        status = "live"
        
    # 3. Parse map scores
    maps_played = []
    for game_div in soup.find_all(class_='vm-stats-game'):
        header = game_div.find(class_='vm-stats-game-header')
        if not header:
            continue
            
        map_name_div = header.find(class_='map')
        if map_name_div:
            map_name = clean_text(map_name_div.get_text()).replace('PICK', '').strip()
            # Strip duration text
            duration_div = map_name_div.find(class_='map-duration')
            if duration_div:
                dur_text = clean_text(duration_div.get_text())
                map_name = map_name.replace(dur_text, '').strip()
            
            # Keep only the last word (Ascent, Split, etc.)
            map_name = map_name.split()[-1] if map_name else "Map"
            
            scores = header.find_all(class_='score')
            if len(scores) >= 2:
                s_a = clean_text(scores[0].get_text())
                s_b = clean_text(scores[1].get_text())
                maps_played.append({
                    "map": map_name,
                    "score_a": s_a,
                    "score_b": s_b
                })
                
    return {
        "series_score_a": score_left,
        "series_score_b": score_right,
        "status": status,
        "maps": maps_played
    }
