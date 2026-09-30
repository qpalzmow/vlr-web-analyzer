import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from app.config import load_tier_config
from app.scraper.http import request_with_retry
from app.scraper.parsers import (
    clean_text, parse_matches_list,
    parse_match_details, parse_live_score, parse_tournament_and_stage
)
def get_matches(strict=False):
    s_keywords, a_keywords = load_tier_config()
    seen_ids = set()
    combined = []

    # 1. Upcoming & Live matches
    try:
        res_live = request_with_retry("https://www.vlr.gg/matches")
        if strict:
            res_live.raise_for_status()
        for m in parse_matches_list(res_live.text, s_keywords, a_keywords):
            if m['id'] not in seen_ids:
                seen_ids.add(m['id'])
                combined.append(m)
    except Exception as e:
        logger.warning('get_matches live request failed: %s', e)
        if strict:
            raise

    # 2. Recent results (pages 1 to 2)
    for page in range(1, 3):
        url = f"https://www.vlr.gg/matches/results/?page={page}" if page > 1 else "https://www.vlr.gg/matches/results"
        try:
            res_results = request_with_retry(url)
            if strict:
                res_results.raise_for_status()
            for m in parse_matches_list(res_results.text, s_keywords, a_keywords):
                if m['id'] not in seen_ids:
                    seen_ids.add(m['id'])
                    combined.append(m)
        except Exception as e:
            logger.warning('get_matches results page %d failed: %s', page, e)
            if strict:
                raise

    # 3. Dynamic Ongoing Major VCT Tournaments (Pacific, Americas, EMEA, China, Masters, Champions)
    try:
        res_events = request_with_retry("https://www.vlr.gg/events")
        if strict:
            res_events.raise_for_status()
        soup_events = BeautifulSoup(res_events.text, "html.parser")
        major_events = []
        for card in soup_events.find_all(class_="event-item"):
            a = card.find("a", href=True) if card.name != "a" else card
            if not a or not a.get("href"):
                continue
            title_elem = card.find(class_="event-item-title") or card.find(class_="wf-title")
            title = clean_text(title_elem.get_text()) if title_elem else clean_text(a.get_text())
            status_elem = card.find(class_="event-item-desc-item-status")
            status = clean_text(status_elem.get_text()).lower() if status_elem else ""
            if ("vct" in title.lower() or "champions" in title.lower() or "masters" in title.lower()) and "ongoing" in status:
                parts = a["href"].split("/")
                if len(parts) >= 3 and parts[2].isdigit():
                    major_events.append({"id": parts[2], "title": title})

        for ev in major_events:
            try:
                ev_res = request_with_retry(f"https://www.vlr.gg/event/matches/{ev['id']}/?series_id=all")
                if strict:
                    ev_res.raise_for_status()
                ev_matches = parse_matches_list(ev_res.text, s_keywords, a_keywords)
                
                region = "Other"
                if re.search(r'\b(champions|masters)\b', ev['title'], re.I):
                    region = "Global"
                elif re.search(r'\b(pacific|korea|japan|apac)\b', ev['title'], re.I):
                    region = "Pacific"
                elif re.search(r'\b(emea|europe)\b', ev['title'], re.I):
                    region = "EMEA"
                elif re.search(r'\b(americas|north america|brazil|latam)\b', ev['title'], re.I):
                    region = "Americas"
                elif re.search(r'\b(china|cn)\b', ev['title'], re.I):
                    region = "China"

                for m in ev_matches:
                    if m['id'] not in seen_ids:
                        seen_ids.add(m['id'])
                        m['tier'] = "S-Tier"
                        m['region'] = region
                        m['tournament'] = ev['title']
                        if ev['title'] not in m['event']:
                            m['event'] = f"{m['event']} {ev['title']}".strip()
                        _, stage, round_name = parse_tournament_and_stage(m['event'])
                        m['stage'] = stage
                        m['round_name'] = round_name
                        combined.append(m)
            except Exception as e:
                logger.warning('Failed to scrape event matches for %s: %s', ev['id'], e)
                if strict:
                    raise

    except Exception as e:
        logger.warning('Failed to discover ongoing major VCT events: %s', e)
        if strict:
            raise

    return combined

def get_match_details(match_url):
    res = request_with_retry(match_url)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, 'html.parser')
    if not soup.select_one('.match-header-vs') or len(soup.select('.match-header-link-name, .wf-title-team')) < 2:
        raise ValueError('Match page structure missing')
    return parse_match_details(res.text, match_url)

def get_event_map_pool(event_id):
    if not event_id:
        return []
    url = f"https://www.vlr.gg/event/agents/{event_id}"
    try:
        res = request_with_retry(url)
    except Exception as e:
        logger.warning('get_event_map_pool request failed: %s', e)
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

def get_team_events(team_id, strict=False):
    if not team_id:
        return []
    url = f"https://www.vlr.gg/team/stats/{team_id}"
    try:
        res = request_with_retry(url)
    except Exception as e:
        logger.warning('get_team_events request failed: %s', e)
        if strict:
            raise
        return []
    if res.status_code != 200:
        if strict:
            raise ValueError(f"Team events returned HTTP {res.status_code}")
        return []

    soup = BeautifulSoup(res.text, 'html.parser')
    events = []
    # Target strictly the tournament event selector, NOT the sub-stage selectors (filter-series, filter-subseries)
    event_select = soup.find('select', attrs={'name': 'event_id'}) or soup.find('select', class_='filter-event')
    if not event_select and not strict:
        selects = soup.find_all('select')
        event_select = selects[0] if selects else None

    if event_select:
        for opt in event_select.find_all('option'):
            val = opt.get('value', '')
            text = clean_text(opt.get_text())
            if val and val != 'all' and text and text != 'All Events':
                if text.lower() in ('playoffs', 'group stage', 'play-ins', 'main event', 'quarterfinals', 'semifinals', 'grand final', 'tournament'):
                    continue
                events.append({"id": val, "name": text})
    elif strict:
        raise ValueError("Team event selector missing")
    return events

def get_live_score(match_url):
    try:
        res = request_with_retry(match_url)
    except Exception as e:
        logger.warning('get_live_score request failed: %s', e)
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    if res.status_code != 200:
        return {"series_score_a": "0", "series_score_b": "0", "status": "error", "maps": []}
    return parse_live_score(res.text)
