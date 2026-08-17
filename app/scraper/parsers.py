import re
from bs4 import BeautifulSoup
from app.config import ALL_KNOWN_MAPS

def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def safe_int(s, default: int = 0) -> int:
    if s is None:
        return default
    s_clean = clean_text(str(s))
    if not s_clean:
        return default
    m = re.search(r'-?\d+', s_clean)
    if m:
        try:
            return int(m.group())
        except ValueError:
            pass
    return default

def safe_float(s, default: float = 0.0) -> float:
    if s is None:
        return default
    s_clean = clean_text(str(s))
    if not s_clean:
        return default
    m = re.search(r'-?\d+(?:\.\d+)?', s_clean)
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return default

def parse_column_indices_from_header(table):
    default_map = {
        'map': 0, 'w': 3, 'l': 4,
        'atk_won': 8, 'atk_lost': 9,
        'def_won': 11, 'def_lost': 12,
    }
    col_map = dict(default_map)
    headers = table.find_all('th')
    if not headers:
        return col_map
    for i, h in enumerate(headers):
        txt = clean_text(h.get_text()).lower()
        cls = ' '.join(h.get('class', []))
        if 'map' in txt:
            col_map['map'] = i
        elif txt == 'w':
            col_map['w'] = i
        elif txt == 'l':
            col_map['l'] = i
        elif 'mod-atk' in cls and txt == 'rw':
            col_map['atk_won'] = i
        elif 'mod-atk' in cls and txt == 'rl':
            col_map['atk_lost'] = i
        elif 'mod-def' in cls and txt == 'rw':
            col_map['def_won'] = i
        elif 'mod-def' in cls and txt == 'rl':
            col_map['def_lost'] = i
    return col_map

def parse_player_column_indices_from_header(table):
    default_map = {
        'agent': 0, 'rounds': 2, 'acs': 4,
        'kills': 11, 'deaths': 12, 'fk': 14, 'fd': 15,
    }
    col_map = dict(default_map)
    headers = table.find_all('th')
    if not headers:
        return col_map
    for i, h in enumerate(headers):
        txt = clean_text(h.get_text()).lower()
        title = h.get('title', '').lower()
        cls = ' '.join(h.get('class', []))
        if 'mod-agent' in cls or title == 'agent':
            col_map['agent'] = i
        elif txt == 'rnd' or 'rounds' in title:
            col_map['rounds'] = i
        elif txt == 'acs' or 'combat score' in title:
            col_map['acs'] = i
        elif txt == 'k' and title == 'total kills':
            col_map['kills'] = i
        elif txt == 'd' and title == 'total deaths':
            col_map['deaths'] = i
        elif txt == 'fk' and 'first kill' in title:
            col_map['fk'] = i
        elif txt == 'fd' and 'first death' in title:
            col_map['fd'] = i
    return col_map

def parse_tournament_and_stage(event_str: str) -> tuple:
    if not event_str:
        return "기타 대회", "기타", ""
    
    tourney_match = re.search(
        r'(VCT\s*\d{4}:?\s*[^–-]+|Game\s*Changers\s*\d{4}:?\s*[^–-]+|Champions\s*\d{4}:?\s*[^–-]+|Masters\s*\d{4}:?\s*[^–-]+|Challengers\s*\d{4}:?\s*[^–-]+|VCL\s*\d{2,4}:?\s*[^–-]+)',
        event_str, re.I
    )
    tournament = tourney_match.group(1).strip() if tourney_match else event_str.strip()
    
    stage = "기타 스테이지"
    if re.search(r'\b(playoffs?|finals?|knockout)\b', event_str, re.I):
        stage = "🏆 플레이오프 (Playoffs)"
    elif re.search(r'\b(play-?ins?|playin|qualifier|lcq)\b', event_str, re.I):
        stage = "⚔️ 플레이인 (Play-Ins)"
    elif re.search(r'\b(group\s*stage|regular\s*season|swiss|week\s*\d+)\b', event_str, re.I):
        stage = "📅 그룹 스테이지 (Group Stage)"
        
    round_info = event_str
    if tourney_match:
        round_info = event_str.replace(tourney_match.group(1), "")
    round_info = re.sub(r'[–-]', ' ', round_info)
    round_info = re.sub(r'\s+', ' ', round_info).strip()
    
    friendly_round = round_info
    if re.search(r'grand\s*final', round_info, re.I):
        friendly_round = "결승전"
    elif re.search(r'upper\s*final', round_info, re.I):
        friendly_round = "상위 결승"
    elif re.search(r'lower\s*final', round_info, re.I):
        friendly_round = "하위 결승"
    elif re.search(r'upper\s*semifinal', round_info, re.I):
        friendly_round = "상위 4강"
    elif re.search(r'lower\s*semifinal', round_info, re.I):
        friendly_round = "하위 4강"
    elif re.search(r'lower\s*round\s*3', round_info, re.I):
        friendly_round = "하위 3R"
    elif re.search(r'lower\s*round\s*2', round_info, re.I):
        friendly_round = "하위 2R"
    elif re.search(r'lower\s*round\s*1', round_info, re.I):
        friendly_round = "하위 1R"
    elif re.search(r'upper\s*quarterfinal', round_info, re.I):
        friendly_round = "상위 8강"
    elif re.search(r'upper\s*round\s*1', round_info, re.I):
        friendly_round = "상위 1R"
    else:
        m_week = re.search(r'week\s*(\d+)', round_info, re.I)
        if m_week:
            friendly_round = f"{m_week.group(1)}주차"

    return tournament, stage, friendly_round

def parse_matches_list(html_text: str, s_keywords: list, a_keywords: list) -> list:
    soup = BeautifulSoup(html_text, 'html.parser')
    matches = []
    labels = soup.find_all(class_='wf-label')
    label_dates = {id(l): clean_text(l.get_text()) for l in labels}

    for card in soup.find_all(class_='wf-card'):
        a_tag = card.find('a', href=True) if card.name != 'a' else card
        if not a_tag or not a_tag.get('href'):
            continue
        href = a_tag['href']
        parts = href.split('/')
        if len(parts) >= 3 and parts[1].isdigit():
            match_id = parts[1]
            full_url = f"https://www.vlr.gg{href}"
            teams = a_tag.find_all(class_=['match-item-vs-team-name', 'match-item-team-name'])
            if not teams:
                teams = a_tag.find_all(class_='match-item-vs-team')
            team_a = clean_text(teams[0].get_text()) if len(teams) > 0 else "TBD"
            team_b = clean_text(teams[1].get_text()) if len(teams) > 1 else "TBD"

            item_item = a_tag.find_parent(class_='match-item') or a_tag
            prev_label = item_item.find_previous(class_='wf-label')
            date_str = label_dates.get(id(prev_label), "") if prev_label else ""

            time_elem = a_tag.find(class_='match-item-time')
            time_str = clean_text(time_elem.get_text()) if time_elem else ""

            eta_elem = a_tag.find(class_='match-item-eta')
            status_str = clean_text(eta_elem.get_text()) if eta_elem else ""

            event_elem = a_tag.find(class_='match-item-event')
            event_text = clean_text(event_elem.get_text()) if event_elem else ""

            tier = "Other"
            if any(k.lower() in event_text.lower() for k in s_keywords):
                tier = "S-Tier"
            elif any(k.lower() in event_text.lower() for k in a_keywords):
                tier = "A-Tier"

            region = "Other"
            if re.search(r'\b(champions|masters)\b', event_text, re.IGNORECASE):
                region = "Global"
            elif re.search(r'\b(pacific|korea|japan|apac|kr|jp)\b', event_text, re.IGNORECASE):
                region = "Pacific"
            elif re.search(r'\b(emea|eu|europe|turkey|cis|tr)\b', event_text, re.IGNORECASE):
                region = "EMEA"
            elif re.search(r'\b(americas|na|north america|latam|brazil|br)\b', event_text, re.IGNORECASE):
                region = "Americas"
            elif re.search(r'\b(china|cn)\b', event_text, re.IGNORECASE):
                region = "China"

            tournament, stage, round_name = parse_tournament_and_stage(event_text)

            matches.append({
                "id": match_id,
                "url": full_url,
                "match_url": full_url,
                "team_a": team_a,
                "team_b": team_b,
                "event": event_text,
                "tournament": tournament,
                "stage": stage,
                "round_name": round_name,
                "region": region,
                "tier": tier,
                "status": status_str,
                "time": time_str,
                "date": date_str
            })
    return matches

def parse_match_details(html_text: str, match_url: str) -> dict:
    soup = BeautifulSoup(html_text, 'html.parser')
    teams = soup.find_all(class_=['wf-title-team', 'match-header-link-name'])
    
    def extract_name(elem):
        med = elem.find(class_='wf-title-med')
        if med:
            alias = med.find('div')
            if alias:
                alias.extract()
            return clean_text(med.get_text())
        return clean_text(elem.get_text())
        
    team_a_name = extract_name(teams[0]) if len(teams) > 0 else "Team A"
    team_b_name = extract_name(teams[1]) if len(teams) > 1 else "Team B"

    team_a_id = ""
    team_b_id = ""
    team_links = soup.find_all('a', class_='match-header-link', href=True)
    if len(team_links) >= 2:
        parts_a = team_links[0]['href'].split('/')
        if len(parts_a) >= 3 and parts_a[1] == 'team':
            team_a_id = parts_a[2]
        parts_b = team_links[1]['href'].split('/')
        if len(parts_b) >= 3 and parts_b[1] == 'team':
            team_b_id = parts_b[2]

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

    match_id = ""
    m_match = re.search(r'/(\d+)(?:/|$)', match_url)
    if m_match:
        match_id = m_match.group(1)

    return {
        "match_id": match_id,
        "team_a_id": team_a_id,
        "team_a_name": team_a_name,
        "team_b_id": team_b_id,
        "team_b_name": team_b_name,
        "event_id": event_id
    }

def parse_live_score(html_text: str) -> dict:
    soup = BeautifulSoup(html_text, 'html.parser')
    score_left = "0"
    score_right = "0"
    vs_container = soup.find(attrs={'data-vlr-score': True}) or soup.find(class_='match-header-vs-score')
    if vs_container:
        if vs_container.has_attr('data-vlr-score'):
            scores = vs_container['data-vlr-score'].split(':')
            if len(scores) >= 2:
                score_left, score_right = scores[0], scores[1]
        else:
            spans = vs_container.find_all('span')
            score_spans = [s for s in spans if any('match-header-vs-score-' in c for c in s.get('class', [])) and 'colon' not in ''.join(s.get('class', []))]
            if len(score_spans) >= 2:
                score_left = clean_text(score_spans[0].get_text())
                score_right = clean_text(score_spans[1].get_text())

    if score_left == "0" and score_right == "0":
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            m = re.search(r'(\d+)\s*[:-]\s*(\d+)', og_desc['content'])
            if m:
                score_left, score_right = m.group(1), m.group(2)

    status = "upcoming"
    header_block = soup.find(class_='match-header')
    header_text = clean_text(header_block.get_text()).lower() if header_block else ""
    if 'final' in header_text:
        status = "final"
    elif 'live' in header_text:
        status = "live"

    known_maps = set(m.lower() for m in ALL_KNOWN_MAPS)
    maps_played = []
    for game_div in soup.find_all(class_='vm-stats-game'):
        game_header = game_div.find(class_='vm-stats-game-header')
        if not game_header:
            continue
        map_name_div = game_header.find(class_='map')
        if map_name_div:
            map_name = ""
            map_name_candidates = map_name_div.find_all(['span', 'div'], class_=True)
            for el in map_name_candidates:
                cand = clean_text(el.get_text())
                if cand.lower() in known_maps:
                    map_name = cand.capitalize()
                    break
            if not map_name:
                full_text = clean_text(map_name_div.get_text(' '))
                for kw in ALL_KNOWN_MAPS:
                    if re.search(r'\b' + re.escape(kw) + r'\b', full_text, re.I):
                        map_name = kw
                        break
            if not map_name:
                map_name = "Map"

            scores = game_header.find_all(class_='score')
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
