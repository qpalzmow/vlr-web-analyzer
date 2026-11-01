import re
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from app.config import load_tier_config
from app.scraper.http import request_with_retry, check_collection_budget, CollectionBudgetExceeded
from app.scraper.parsers import (
    clean_text, parse_matches_list,
    parse_match_details, parse_live_score, parse_tournament_and_stage
)
def get_matches(strict=False, with_sources=False):
    if with_sources:
        return _get_matches_with_sources()
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
                m['status_code'] = 'final'
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


def _parse_match_source(html, s_keywords, a_keywords):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('.match-item, .wf-card, .matches-container, .wf-label'):
        raise ValueError('Match list page structure missing')
    return parse_matches_list(html, s_keywords, a_keywords)


def _discover_major_events(html):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('.event-item, .events-container, .event-filter, .events-subnav'):
        raise ValueError('Event list page structure missing')
    events = {}
    for card in soup.find_all(class_='event-item'):
        anchor = card if card.name == 'a' else card.find('a', href=True)
        if not anchor or not anchor.get('href'):
            continue
        title_node = card.find(class_='event-item-title') or card.find(class_='wf-title')
        title = clean_text((title_node or anchor).get_text())
        status_node = card.find(class_='event-item-desc-item-status')
        status = clean_text(status_node.get_text()).lower() if status_node else ''
        event_id = re.match(r'^/event/(\d+)(?:/|$)', anchor['href'])
        if event_id and re.search(r'vct|champions|masters', title, re.I) and 'ongoing' in status:
            events[event_id[1]] = {'id': event_id[1], 'title': title}
    return list(events.values())


def _event_match_rows(html, event, s_keywords, a_keywords):
    rows = _parse_match_source(html, s_keywords, a_keywords)
    region = 'Other'
    for pattern, value in ((r'\b(champions|masters)\b', 'Global'),
                           (r'\b(pacific|korea|japan|apac)\b', 'Pacific'),
                           (r'\b(emea|europe)\b', 'EMEA'),
                           (r'\b(americas|north america|brazil|latam)\b', 'Americas'),
                           (r'\b(china|cn)\b', 'China')):
        if re.search(pattern, event['title'], re.I):
            region = value
            break
    for row in rows:
        row['tier'], row['region'], row['tournament'] = 'S-Tier', region, event['title']
        if event['title'] not in row['event']:
            row['event'] = f"{row['event']} {event['title']}".strip()
        _, row['stage'], row['round_name'] = parse_tournament_and_stage(row['event'])
    return rows


def _get_matches_with_sources():
    """Collect provenance without discarding required lists on a later failure.

    This does not decide whether partial data is publishable. The catalog uses
    required-source completeness and previous ownership to make that decision.
    """
    s_keywords, a_keywords = load_tier_config()
    sources, failures, combined = {}, [], {}

    def collect(source_id, url, parser, *, required=False, owns_matches=True):
        source = {'required': required, 'status': 'failed', 'match_ids': [], 'collected_at': None}
        sources[source_id] = source
        try:
            check_collection_budget()
            response = request_with_retry(url)
            response.raise_for_status()
        except Exception as error:
            reason = 'budget_exceeded' if isinstance(error, CollectionBudgetExceeded) else 'http_error'
        else:
            try:
                result = parser(response.text)
                check_collection_budget()
            except Exception as error:
                reason = 'budget_exceeded' if isinstance(error, CollectionBudgetExceeded) else 'parse_error'
            else:
                source.update(status='completed', collected_at=datetime.now(timezone.utc).isoformat())
                if owns_matches:
                    source['match_ids'] = list(dict.fromkeys(str(row['id']) for row in result))
                    for row in result:
                        match_id = str(row['id'])
                        if match_id not in combined:
                            combined[match_id] = {**row, 'source_ids': []}
                        if source_id not in combined[match_id]['source_ids']:
                            combined[match_id]['source_ids'].append(source_id)
                else:
                    source['event_ids'] = [str(event['id']) for event in result]
                return result
        source['reason'] = reason
        failures.append({'kind': 'source', 'source': source_id, 'id': source_id, 'reason': reason})
        logger.warning('Match source %s failed: %s', source_id, reason)
        return []

    parse_rows = lambda html: _parse_match_source(html, s_keywords, a_keywords)
    collect('upcoming', 'https://www.vlr.gg/matches', parse_rows, required=True)
    for page in (1, 2):
        url = 'https://www.vlr.gg/matches/results' + (f'/?page={page}' if page > 1 else '')
        def parse_results(html):
            rows = parse_rows(html)
            for row in rows:
                row['status_code'] = 'final'
            return rows
        collect(f'results:{page}', url, parse_results, required=True)
    events = collect('events', 'https://www.vlr.gg/events', _discover_major_events, owns_matches=False)
    for event in events:
        collect(f"event:{event['id']}", f"https://www.vlr.gg/event/matches/{event['id']}/?series_id=all",
                lambda html, event=event: _event_match_rows(html, event, s_keywords, a_keywords))
    return {'matches': list(combined.values()), 'sources': sources, 'failures': failures,
            'required_complete': all(sources[key]['status'] == 'completed'
                                     for key in ('upcoming', 'results:1', 'results:2'))}

def get_match_details(match_url):
    res = request_with_retry(match_url)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, 'html.parser')
    if not soup.select_one('.match-header-vs') or len(soup.select('.match-header-link-name, .wf-title-team')) < 2:
        raise ValueError('Match page structure missing')
    return parse_match_details(res.text, match_url)

def get_event_map_pool(event_id, strict=False):
    if not event_id:
        return []
    url = f"https://www.vlr.gg/event/agents/{event_id}"
    try:
        res = request_with_retry(url)
    except Exception as e:
        logger.warning('get_event_map_pool request failed: %s', e)
        if strict:
            raise
        return []
    if res.status_code != 200:
        if strict:
            res.raise_for_status()
            raise ValueError(f'Event map pool returned HTTP {res.status_code}')
        return []

    from app.config import ALL_KNOWN_MAPS
    soup = BeautifulSoup(res.text, 'html.parser')
    detected = set()

    containers = soup.find_all(class_=['mod-agents', 'vm-stats-container', 'mod-team-maps', 'mod-map-pool'])
    # The public event-agents page uses a global pick-rate table. Restrict this
    # fallback to that table rather than treating map names anywhere as data.
    containers.extend(soup.select('table.mod-pr-global'))
    if strict and not containers:
        raise ValueError('Event map pool page structure missing')
    for container in containers:
        for cell in container.find_all(['th', 'td', 'div', 'span']):
            cell_text = clean_text(cell.get_text())
            if not cell_text:
                continue
            for m in ALL_KNOWN_MAPS:
                if m not in detected and re.search(r'\b' + re.escape(m) + r'\b', cell_text, re.I):
                    detected.add(m)

    if not detected and not strict:
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
            res.raise_for_status()
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
